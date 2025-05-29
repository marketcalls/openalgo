import asyncio
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
        self.running = False
        
        # ZeroMQ context for subscribing to broker adapters
        self.context = zmq.asyncio.Context()
        self.socket = self.context.socket(zmq.SUB)
        self.socket.connect("tcp://localhost:5555")  # Connect to broker adapter publisher
        
        # Set up ZeroMQ subscriber to receive all messages
        self.socket.setsockopt(zmq.SUBSCRIBE, b"")  # Subscribe to all topics
    
    async def start(self):
        """Start the WebSocket server and ZeroMQ listener"""
        self.running = True
        
        try:
            # Start ZeroMQ listener
            logger.info("Initializing ZeroMQ listener task")
            asyncio.create_task(self.zmq_listener())
            
            # Start WebSocket server
            stop = asyncio.Future()  # Used to stop the server
            
            # Handle graceful shutdown
            # Windows doesn't support add_signal_handler, so we'll use a simpler approach
            loop = asyncio.get_event_loop()
            try:
                for sig in (signal.SIGINT, signal.SIGTERM):
                    loop.add_signal_handler(sig, stop.set_result, None)
            except NotImplementedError:
                # On Windows, we'll just rely on the KeyboardInterrupt exception
                logger.info("Signal handlers not supported on this platform. Using fallback mechanism.")
            
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
    
    async def authenticate_client(self, client_id, data):
        """
        Authenticate a client using their API key
        
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
        
        # Create or reuse broker adapter
        if user_id not in self.broker_adapters:
            # In a real implementation, you would determine the broker from the user's profile
            broker_name = "angel"  # Hardcoded for now
            
            try:
                # Create broker adapter
                adapter = create_broker_adapter(broker_name)
                if not adapter:
                    await self.send_error(client_id, "BROKER_ERROR", f"Failed to create adapter for broker: {broker_name}")
                    return
                
                # Initialize and connect
                adapter.initialize(broker_name, user_id)
                adapter.connect()
                
                # Store the adapter
                self.broker_adapters[user_id] = adapter
            except Exception as e:
                logger.error(f"Failed to create broker adapter: {e}")
                await self.send_error(client_id, "BROKER_ERROR", str(e))
                return
        
        # Send success response
        await self.send_message(client_id, {
            "type": "auth",
            "status": "success",
            "message": "Authentication successful"
        })
    
    async def subscribe_client(self, client_id, data):
        """
        Subscribe a client to market data
        
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
                    "depth_level": depth_level
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
                    "depth": response.get("actual_depth", depth_level)
                })
            else:
                subscription_success = False
                # Add to failed subscriptions
                subscription_responses.append({
                    "symbol": symbol,
                    "exchange": exchange,
                    "status": "error",
                    "message": response.get("message", "Subscription failed")
                })
        
        # Send combined response
        await self.send_message(client_id, {
            "type": "subscribe",
            "status": "success" if subscription_success else "partial",
            "subscriptions": subscription_responses,
            "message": "Subscription processing complete" 
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
                                "status": "success"
                            })
                        else:
                            failed_unsubscriptions.append({
                                "symbol": symbol,
                                "exchange": exchange,
                                "status": "error",
                                "message": response.get("message", "Unsubscription failed")
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
                            "mode": mode
                        }
                        subscription_key = json.dumps(subscription_info)
                        if subscription_key in self.subscriptions[client_id]:
                            self.subscriptions[client_id].remove(subscription_key)
                    
                    successful_unsubscriptions.append({
                        "symbol": symbol,
                        "exchange": exchange,
                        "status": "success"
                    })
                else:
                    failed_unsubscriptions.append({
                        "symbol": symbol,
                        "exchange": exchange,
                        "status": "error",
                        "message": response.get("message", "Unsubscription failed")
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
            "failed": failed_unsubscriptions
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
                    [topic, data] = await asyncio.wait_for(
                        self.socket.recv_multipart(),
                        timeout=0.1
                    )
                except asyncio.TimeoutError:
                    # No message received within timeout, continue the loop
                    continue
                
                # Parse the message
                topic_str = topic.decode('utf-8')
                data_str = data.decode('utf-8')
                market_data = json.loads(data_str)
                
                # Extract topic components
                # Format: EXCHANGE_SYMBOL_MODE
                parts = topic_str.split('_')
                if len(parts) < 3:
                    logger.warning(f"Invalid topic format: {topic_str}")
                    continue
                
                exchange = parts[0]
                symbol = parts[1]
                mode_str = parts[2]
                
                # Map mode string to mode number
                mode_map = {"LTP": 1, "QUOTE": 2, "DEPTH": 3}  # Mode 3 is Snap Quote (includes depth data)
                mode = mode_map.get(mode_str)
                
                if not mode:
                    logger.warning(f"Invalid mode in topic: {mode_str}")
                    continue
                
                # Find clients subscribed to this data
                for client_id, subscriptions in self.subscriptions.items():
                    for sub_json in subscriptions:
                        sub = json.loads(sub_json)
                        
                        # Improved matching logic to handle both string and integer modes
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
                                "data": market_data
                            })
            
            except Exception as e:
                logger.error(f"Error in ZeroMQ listener: {e}")
                # Continue running despite errors
                await asyncio.sleep(1)

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
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Server error: {e}\n{error_details}")
    finally:
        await proxy.stop()

if __name__ == "__main__":
    asyncio.run(main())
