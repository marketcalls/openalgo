import asyncio as aio
import websockets
import json
from utils.logging import get_logger, highlight_url
import signal
import zmq
import zmq.asyncio
import threading
import time
import os
import socket
from typing import Dict, Set, Any, Optional
from dotenv import load_dotenv

from .port_check import is_port_in_use, find_available_port
from database.auth_db import get_broker_name
from sqlalchemy import text
from database.auth_db import verify_api_key
from .broker_factory import create_broker_adapter
from .base_adapter import BaseBrokerWebSocketAdapter

logger = get_logger("websocket_proxy")

mode_mapping = {
    "LTP": 1,
    "Quote": 2, 
    "Depth": 3
}
mode_to_str = {v: k for k, v in mode_mapping.items()}

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
        
        if is_port_in_use(host, port, wait_time=2.0):
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
        
        self.clients = {}
        self.subscriptions = {}
        self.broker_adapters = {}
        self.user_mapping = {}
        self.user_broker_mapping = {}
        
        self.global_subscriptions = {}
        self.subscription_refs = {}
        self.subscription_lock = aio.Lock()
        self.user_lock = aio.Lock()
        self.adapter_lock = aio.Lock()
        self.zmq_send_lock = aio.Lock()
        
        self.running = False
        
        self.context = zmq.asyncio.Context()
        self.socket = self.context.socket(zmq.SUB)
        ZMQ_HOST = os.getenv('ZMQ_HOST', '127.0.0.1')
        ZMQ_PORT = os.getenv('ZMQ_PORT')
        self.socket.connect(f"tcp://{ZMQ_HOST}:{ZMQ_PORT}")
        self.socket.setsockopt(zmq.SUBSCRIBE, b"")
    
    def _get_subscription_key(self, user_id: str, symbol: str, exchange: str, mode: int) -> tuple:
        """Get subscription key for global tracking"""
        return (user_id, symbol, exchange, mode)
    
    def _add_global_subscription(self, client_id: str, user_id: str, symbol: str, exchange: str, mode: int):
        """Add a global subscription and update reference count"""
        key = self._get_subscription_key(user_id, symbol, exchange, mode)
        
        if key not in self.global_subscriptions:
            self.global_subscriptions[key] = set()
            self.subscription_refs[key] = 0
        
        self.global_subscriptions[key].add(client_id)
        self.subscription_refs[key] += 1
        
        logger.debug(f"Added global subscription {key}, ref_count: {self.subscription_refs[key]}")
    
    def _remove_global_subscription(self, client_id: str, user_id: str, symbol: str, exchange: str, mode: int) -> bool:
        """Remove a global subscription and return True if this was the last client"""
        key = self._get_subscription_key(user_id, symbol, exchange, mode)
        
        if key not in self.global_subscriptions:
            return False
        
        self.global_subscriptions[key].discard(client_id)
        self.subscription_refs[key] -= 1
        
        is_last_client = self.subscription_refs[key] <= 0
        
        if is_last_client:
            del self.global_subscriptions[key]
            del self.subscription_refs[key]
            logger.debug(f"Removed last global subscription {key}")
        else:
            logger.debug(f"Removed global subscription {key}, remaining ref_count: {self.subscription_refs[key]}")
        
        return is_last_client
    
    def _get_remaining_clients(self, user_id: str, symbol: str, exchange: str, mode: int) -> set:
        """Get remaining clients for a subscription"""
        key = self._get_subscription_key(user_id, symbol, exchange, mode)
        return self.global_subscriptions.get(key, set())
    
    async def start(self):
        """Start the WebSocket server and ZeroMQ listener"""
        self.running = True
        
        try:
            logger.info("Initializing ZeroMQ listener task")
            
            loop = aio.get_running_loop()
            
            zmq_task = loop.create_task(self.zmq_listener())
            
            stop = aio.Future()
            
            async def monitor_shutdown():
                while self.running:
                    await aio.sleep(0.5)
                stop.set_result(None)
            
            monitor_task = aio.create_task(monitor_shutdown())
            
            try:
                loop = aio.get_running_loop()
                
                if threading.current_thread() is threading.main_thread():
                    try:
                        for sig in (signal.SIGINT, signal.SIGTERM):
                            loop.add_signal_handler(sig, stop.set_result, None)
                        logger.info("Signal handlers registered successfully")
                    except (NotImplementedError, RuntimeError) as e:
                        logger.info(f"Signal handlers not registered: {e}. Using fallback mechanism.")
                else:
                    logger.info("Running in a non-main thread. Signal handlers will not be used.")
            except RuntimeError:
                logger.info("No running event loop found for signal handlers")
            
            highlighted_address = highlight_url(f"{self.host}:{self.port}")
            logger.info(f"Starting WebSocket server on {highlighted_address}")
            
            try:
                self.server = await websockets.serve(
                    self.handle_client, 
                    self.host, 
                    self.port,
                    reuse_port=True if hasattr(socket, 'SO_REUSEPORT') else False
                )
                
                highlighted_success_address = highlight_url(f"{self.host}:{self.port}")
                logger.info(f"WebSocket server successfully started on {highlighted_success_address}")
                
                await stop
                
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
            if hasattr(self, 'server') and self.server:
                try:
                    logger.info("Closing WebSocket server...")
                    try:
                        self.server.close()
                        await self.server.wait_closed()
                        logger.info("WebSocket server closed and port released")
                    except RuntimeError as e:
                        if "attached to a different loop" in str(e):
                            logger.warning(f"WebSocket server cleanup skipped due to event loop mismatch: {e}")
                            try:
                                self.server.close()
                            except:
                                pass
                        else:
                            raise
                except Exception as e:
                    logger.error(f"Error closing WebSocket server: {e}")
            
            close_tasks = []
            for client_id, websocket in self.clients.items():
                try:
                    if hasattr(websocket, 'open') and websocket.open:
                        close_tasks.append(websocket.close())
                except Exception as e:
                    logger.error(f"Error preparing to close client {client_id}: {e}")
            
            if close_tasks:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*close_tasks, return_exceptions=True),
                        timeout=2.0
                    )
                except asyncio.TimeoutError:
                    logger.warning("Timeout waiting for client connections to close")
            
            for user_id, adapter in self.broker_adapters.items():
                try:
                    adapter.disconnect()
                except Exception as e:
                    logger.error(f"Error disconnecting adapter for user {user_id}: {e}")
            
            if hasattr(self, 'socket') and self.socket:
                try:
                    self.socket.setsockopt(zmq.LINGER, 0)
                    self.socket.close()
                except Exception as e:
                    logger.error(f"Error closing ZMQ socket: {e}")
            
            if hasattr(self, 'context') and self.context:
                try:
                    self.context.term()
                except Exception as e:
                    logger.error(f"Error terminating ZMQ context: {e}")
            
            logger.info("WebSocket server stopped and resources cleaned up")
            
        except Exception as e:
            logger.error(f"Error during WebSocket server stop: {e}")
    
    async def handle_client(self, websocket):
        """
        Handle a client connection
        
        Args:
            websocket: The WebSocket connection
        """
        client_id = id(websocket)
        self.clients[client_id] = websocket
        self.subscriptions[client_id] = set()
        
        path = getattr(websocket, 'path', '/unknown')
        logger.info(f"Client connected: {client_id} from path: {path}")
        
        try:
            async for message in websocket:
                try:
                    logger.debug(f"Received message from client {client_id}: {message}")
                    await self.process_client_message(client_id, message)
                except Exception as e:
                    logger.exception(f"Error processing message from client {client_id}: {e}")
                    try:
                        await self.send_error(client_id, "PROCESSING_ERROR", str(e))
                    except:
                        pass
        except websockets.exceptions.ConnectionClosed as e:
            logger.info(f"Client disconnected: {client_id}, code: {e.code}, reason: {e.reason}")
        except Exception as e:
            logger.exception(f"Unexpected error handling client {client_id}: {e}")
        finally:
            await self.cleanup_client(client_id)
    
    async def cleanup_client(self, client_id):
        """
        Clean up client resources when they disconnect
        
        Args:
            client_id: Client ID to clean up
        """
        async with self.subscription_lock:
            if client_id in self.clients:
                del self.clients[client_id]
            
            if client_id in self.subscriptions:
                subscriptions = self.subscriptions[client_id].copy()
                for sub_json in subscriptions:
                    try:
                        sub_info = json.loads(sub_json)
                        symbol = sub_info.get('symbol')
                        exchange = sub_info.get('exchange')
                        mode = sub_info.get('mode')
                        
                        user_id = self.user_mapping.get(client_id)
                        if user_id and user_id in self.broker_adapters:
                            is_last_client = self._remove_global_subscription(client_id, user_id, symbol, exchange, mode)
                            
                            if is_last_client:
                                adapter = self.broker_adapters[user_id]
                                adapter.unsubscribe(symbol, exchange, mode)
                                logger.info(f"Last client disconnected, unsubscribed from {symbol}.{exchange}.{mode_to_str.get(mode, mode)}")
                            else:
                                logger.info(f"Client disconnected from {symbol}.{exchange}.{mode_to_str.get(mode, mode)}, but other clients still subscribed")
                    except json.JSONDecodeError as e:
                        logger.exception(f"Error parsing subscription: {sub_json}, Error: {e}")
                    except Exception as e:
                        logger.exception(f"Error processing subscription: {e}")
                        continue
                
                del self.subscriptions[client_id]
        
        async with self.user_lock:
            if client_id in self.user_mapping:
                user_id = self.user_mapping[client_id]
                
                is_last_client = True
                for other_client_id, other_user_id in self.user_mapping.items():
                    if other_client_id != client_id and other_user_id == user_id:
                        is_last_client = False
                        break
                
                if is_last_client and user_id in self.broker_adapters:
                    adapter = self.broker_adapters[user_id]
                    broker_name = self.user_broker_mapping.get(user_id)

                    if broker_name in ['flattrade', 'shoonya'] and hasattr(adapter, 'unsubscribe_all'):
                        logger.info(f"{broker_name.title()} adapter for user {user_id}: last client disconnected. Unsubscribing all symbols instead of disconnecting.")
                        adapter.unsubscribe_all()
                    else:
                        logger.info(f"Last client for user {user_id} disconnected. Disconnecting {broker_name or 'unknown broker'} adapter.")
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
            logger.debug(f"Parsed message from client {client_id}: {data}")
            
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
            from database.auth_db import get_broker_name
            from sqlalchemy import text
            
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
                valid_brokers = os.getenv('VALID_BROKERS', 'angel').split(',')
                broker_name = valid_brokers[0].strip() if valid_brokers else 'angel'
                logger.warning(f"No broker found in database for user {user_id}, using fallback: {broker_name}")
            
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
            logger.exception(f"Error getting broker configuration for user {user_id}: {e}")
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
        
        user_id = verify_api_key(api_key)
        
        if not user_id:
            await self.send_error(client_id, "AUTHENTICATION_ERROR", "Invalid API key")
            return
        
        async with self.user_lock:
            self.user_mapping[client_id] = user_id
        
        broker_name = get_broker_name(api_key)
        
        if not broker_name:
            await self.send_error(client_id, "BROKER_ERROR", "No broker configuration found for user")
            return
        
        async with self.user_lock:
            self.user_broker_mapping[user_id] = broker_name
        
        async with self.adapter_lock:
            if user_id not in self.broker_adapters:
                try:
                    adapter = create_broker_adapter(broker_name)
                    if not adapter:
                        await self.send_error(client_id, "BROKER_ERROR", f"Failed to create adapter for broker: {broker_name}")
                        return
                    
                    initialization_result = adapter.initialize(broker_name, user_id)
                    if initialization_result and not initialization_result.get('success', True):
                        error_msg = initialization_result.get('error', 'Failed to initialize broker adapter')
                        await self.send_error(client_id, "BROKER_INIT_ERROR", error_msg)
                        return
                    
                    connect_result = adapter.connect()
                    if connect_result and not connect_result.get('success', True):
                        error_msg = connect_result.get('error', 'Failed to connect to broker')
                        await self.send_error(client_id, "BROKER_CONNECTION_ERROR", error_msg)
                        return
                    
                    self.broker_adapters[user_id] = adapter
                    
                    logger.info(f"Successfully created and connected {broker_name} adapter for user {user_id}")
                    
                except Exception as e:
                    logger.error(f"Failed to create broker adapter for {broker_name}: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    await self.send_error(client_id, "BROKER_ERROR", str(e))
                    return
        
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
    
    async def get_broker_info(self, client_id):
        """
        Get broker information for an authenticated client
        
        Args:
            client_id: ID of the client
        """
        if client_id not in self.user_mapping:
            await self.send_error(client_id, "NOT_AUTHENTICATED", "You must authenticate first")
            return
        
        user_id = self.user_mapping[client_id]
        broker_name = self.user_broker_mapping.get(user_id)
        
        if not broker_name:
            await self.send_error(client_id, "BROKER_ERROR", "Broker information not available")
            return
        
        adapter_status = "disconnected"
        if user_id in self.broker_adapters:
            adapter = self.broker_adapters[user_id]
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
        if client_id not in self.user_mapping:
            await self.send_error(client_id, "NOT_AUTHENTICATED", "You must authenticate first")
            return
        
        symbols = data.get("symbols") or []
        mode_str = data.get("mode", "Quote")
        depth_level = data.get("depth", 5)
        
        mode = mode_mapping.get(mode_str, mode_str) if isinstance(mode_str, str) else mode_str
        
        if not symbols and (data.get("symbol") and data.get("exchange")):
            symbols = [{
                "symbol": data.get("symbol"),
                "exchange": data.get("exchange")
            }]
        
        if not symbols:
            await self.send_error(client_id, "INVALID_PARAMETERS", "At least one symbol must be specified")
            return
        
        user_id = self.user_mapping[client_id]
        if user_id not in self.broker_adapters:
            await self.send_error(client_id, "BROKER_ERROR", "Broker adapter not found")
            return
        
        adapter = self.broker_adapters[user_id]
        broker_name = self.user_broker_mapping.get(user_id, "unknown")
        
        subscription_responses = []
        subscription_success = True
        
        async with self.subscription_lock:
            for symbol_info in symbols:
                symbol = symbol_info.get("symbol")
                exchange = symbol_info.get("exchange")
                
                if not symbol or not exchange:
                    continue
                
                client_already_subscribed = False
                if client_id in self.subscriptions:
                    for sub_json in self.subscriptions[client_id]:
                        try:
                            sub_info = json.loads(sub_json)
                            if (sub_info.get("symbol") == symbol and 
                                sub_info.get("exchange") == exchange and 
                                sub_info.get("mode") == mode):
                                client_already_subscribed = True
                                break
                        except json.JSONDecodeError:
                            continue
                
                if client_already_subscribed:
                    subscription_responses.append({
                        "symbol": symbol,
                        "exchange": exchange,
                        "status": "warning",
                        "message": "Already subscribed to this symbol/exchange/mode",
                        "mode": mode_str,
                        "broker": broker_name
                    })
                    continue
                
                key = self._get_subscription_key(user_id, symbol, exchange, mode)
                is_first_subscription = key not in self.global_subscriptions
                
                self._add_global_subscription(client_id, user_id, symbol, exchange, mode)
                
                response = None
                if is_first_subscription:
                    try:
                        response = adapter.subscribe(symbol, exchange, mode, depth_level)
                        
                        if response.get("status") != "success":
                            self._remove_global_subscription(client_id, user_id, symbol, exchange, mode)
                            subscription_success = False
                            subscription_responses.append({
                                "symbol": symbol,
                                "exchange": exchange,
                                "status": "error",
                                "message": response.get("message", "Subscription failed"),
                                "mode": mode_str,
                                "broker": broker_name
                            })
                            continue
                        else:
                            logger.info(f"First client subscribed to {symbol}.{exchange}.{mode_to_str.get(mode, mode)}, broker subscribe successful")
                    except Exception as e:
                        self._remove_global_subscription(client_id, user_id, symbol, exchange, mode)
                        subscription_success = False
                        subscription_responses.append({
                            "symbol": symbol,
                            "exchange": exchange,
                            "status": "error",
                            "message": f"Subscription error: {str(e)}",
                            "mode": mode_str,
                            "broker": broker_name
                        })
                        logger.error(f"Exception during broker subscribe: {e}")
                        continue
                else:
                    response = {"status": "success", "message": "Already subscribed by other clients"}
                    logger.info(f"Client subscribed to {symbol}.{exchange}.{mode_to_str.get(mode, mode)}, but other clients already subscribed")
                
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
                
                subscription_responses.append({
                    "symbol": symbol,
                    "exchange": exchange,
                    "status": "success",
                    "mode": mode_str,
                    "depth": response.get("actual_depth", depth_level),
                    "broker": broker_name,
                    "is_first_subscription": is_first_subscription
                })
        
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
        if client_id not in self.user_mapping:
            await self.send_error(client_id, "NOT_AUTHENTICATED", "You must authenticate first")
            return
        
        is_unsubscribe_all = data.get("type") == "unsubscribe_all" or data.get("action") == "unsubscribe_all"
        
        symbols = data.get("symbols") or []
        
        if not symbols and not is_unsubscribe_all and (data.get("symbol") and data.get("exchange")):
            symbols = [{
                "symbol": data.get("symbol"),
                "exchange": data.get("exchange"),
                "mode": data.get("mode", 2)
            }]
        
        if not symbols and not is_unsubscribe_all:
            await self.send_error(client_id, "INVALID_PARAMETERS", "Either symbols or unsubscribe_all is required")
            return
        
        user_id = self.user_mapping[client_id]
        if user_id not in self.broker_adapters:
            await self.send_error(client_id, "BROKER_ERROR", "Broker adapter not found")
            return
        
        adapter = self.broker_adapters[user_id]
        broker_name = self.user_broker_mapping.get(user_id, "unknown")
        
        successful_unsubscriptions = []
        failed_unsubscriptions = []
        
        async with self.subscription_lock:
            if is_unsubscribe_all:
                if client_id not in self.subscriptions or not self.subscriptions[client_id]:
                    await self.send_message(client_id, {
                        "type": "unsubscribe",
                        "status": "success",
                        "message": "No active subscriptions to unsubscribe from",
                        "successful": [],
                        "failed": [],
                        "broker": broker_name
                    })
                    return
                
                all_subscriptions = []
                for sub_json in self.subscriptions[client_id]:
                    try:
                        sub_dict = json.loads(sub_json)
                        all_subscriptions.append(sub_dict)
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse subscription: {sub_json}")
                
                for sub in all_subscriptions:
                    symbol = sub.get("symbol")
                    exchange = sub.get("exchange")
                    mode = sub.get("mode")
                    
                    if symbol and exchange and mode is not None:
                        is_last_client = self._remove_global_subscription(client_id, user_id, symbol, exchange, mode)
                        
                        response = None
                        if is_last_client:
                            try:
                                response = adapter.unsubscribe(symbol, exchange, mode)
                                logger.info(f"Last client unsubscribed from {symbol}.{exchange}.{mode_to_str.get(mode, mode)}, calling broker unsubscribe")
                            except Exception as e:
                                response = {"status": "error", "message": str(e)}
                                logger.error(f"Exception during broker unsubscribe: {e}")
                        else:
                            response = {"status": "success", "message": "Unsubscribed from client, but other clients still subscribed"}
                            logger.info(f"Client unsubscribed from {symbol}.{exchange}.{mode_to_str.get(mode, mode)}, but other clients still subscribed")
                        
                        if response and response.get("status") == "success":
                            successful_unsubscriptions.append({
                                "symbol": symbol,
                                "exchange": exchange,
                                "status": "success",
                                "broker": broker_name,
                                "was_last_client": is_last_client
                            })
                        else:
                            failed_unsubscriptions.append({
                                "symbol": symbol,
                                "exchange": exchange,
                                "status": "error",
                                "message": response.get("message", "Unsubscription failed") if response else "No response from adapter",
                                "broker": broker_name
                            })
                
                self.subscriptions[client_id].clear()
            else:
                for symbol_info in symbols:
                    symbol = symbol_info.get("symbol")
                    exchange = symbol_info.get("exchange")
                    mode = symbol_info.get("mode", 2)
                    
                    if not symbol or not exchange:
                        continue
                    
                    subscription_exists = False
                    if client_id in self.subscriptions:
                        for sub_json in self.subscriptions[client_id]:
                            try:
                                sub_data = json.loads(sub_json)
                                if (sub_data.get("symbol") == symbol and 
                                    sub_data.get("exchange") == exchange and 
                                    sub_data.get("mode") == mode):
                                    subscription_exists = True
                                    break
                            except json.JSONDecodeError:
                                continue
                    
                    if not subscription_exists:
                        failed_unsubscriptions.append({
                            "symbol": symbol,
                            "exchange": exchange,
                            "status": "error",
                            "message": "Client is not subscribed to this symbol/exchange/mode",
                            "mode": mode_to_str.get(mode, mode),
                            "broker": broker_name
                        })
                        logger.warning(f"Attempted to unsubscribe from non-existent subscription: {symbol}.{exchange}.{mode_to_str.get(mode, mode)}")
                        continue
                    
                    is_last_client = self._remove_global_subscription(client_id, user_id, symbol, exchange, mode)
                    
                    response = None
                    if is_last_client:
                        try:
                            response = adapter.unsubscribe(symbol, exchange, mode)
                            logger.info(f"Last client unsubscribed from {symbol}.{exchange}.{mode_to_str.get(mode, mode)}, calling broker unsubscribe")
                        except Exception as e:
                            response = {"status": "error", "message": str(e)}
                            logger.error(f"Exception during broker unsubscribe: {e}")
                    else:
                        response = {"status": "success", "message": "Unsubscribed from client, but other clients still subscribed"}
                        logger.info(f"Client unsubscribed from {symbol}.{exchange}.{mode_to_str.get(mode, mode)}, but other clients still subscribed")
                    
                    if response and response.get("status") == "success":
                        if client_id in self.subscriptions:
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
                            "broker": broker_name,
                            "was_last_client": is_last_client
                        })
                    else:
                        failed_unsubscriptions.append({
                            "symbol": symbol,
                            "exchange": exchange,
                            "status": "error",
                            "message": response.get("message", "Unsubscription failed") if response else "No response from adapter",
                            "mode": mode_to_str.get(mode, mode),
                            "broker": broker_name
                        })
        
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
                if not self.running:
                    break
                    
                try:
                    [topic, data] = await aio.wait_for(
                        self.socket.recv_multipart(),
                        timeout=0.1
                    )
                except aio.TimeoutError:
                    continue
                
                topic_str = topic.decode('utf-8')
                data_str = data.decode('utf-8')
                market_data = json.loads(data_str)
                
                parts = topic_str.split('_')
                
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
                elif len(parts) >= 5 and parts[1] == "INDEX":
                    broker_name = parts[0]
                    exchange = f"{parts[1]}_{parts[2]}"
                    symbol = parts[3]
                    mode_str = parts[4]
                elif len(parts) >= 4:
                    broker_name = parts[0]
                    exchange = parts[1]
                    symbol = parts[2]
                    mode_str = parts[3]
                elif len(parts) >= 3:
                    broker_name = "unknown"
                    exchange = parts[0]
                    symbol = parts[1] 
                    mode_str = parts[2]
                else:
                    logger.warning(f"Invalid topic format: {topic_str}")
                    continue
                
                mode_map = {"LTP": 1, "QUOTE": 2, "DEPTH": 3}
                mode = mode_map.get(mode_str)
                
                if not mode:
                    logger.warning(f"Invalid mode in topic: {mode_str}")
                    continue
                
                async with self.subscription_lock:
                    subscriptions_snapshot = list(self.subscriptions.items())
                
                for client_id, subscriptions in subscriptions_snapshot:
                    user_id = self.user_mapping.get(client_id)
                    if not user_id:
                        continue
                    
                    client_broker = self.user_broker_mapping.get(user_id)
                    if broker_name != "unknown" and client_broker and client_broker != broker_name:
                        continue
                    
                    subscriptions_list = list(subscriptions)
                    for sub_json in subscriptions_list:
                        try:
                            sub = json.loads(sub_json)
                            
                            if (sub.get("symbol") == symbol and 
                                sub.get("exchange") == exchange and 
                                (sub.get("mode") == mode or 
                                 (mode_str == "LTP" and sub.get("mode") == 1) or
                                 (mode_str == "QUOTE" and sub.get("mode") == 2) or
                                 (mode_str == "DEPTH" and sub.get("mode") == 3))):
                                
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
                await aio.sleep(1)

async def main():
    """Main entry point for running the WebSocket proxy server"""
    proxy = None
    
    try:
        load_dotenv()
        
        ws_host = os.getenv('WEBSOCKET_HOST', '127.0.0.1')
        ws_port = int(os.getenv('WEBSOCKET_PORT', '8765'))
        
        proxy = WebSocketProxy(host=ws_host, port=ws_port)
        
        await proxy.start()
        
    except KeyboardInterrupt:
        logger.info("Server stopped by user (KeyboardInterrupt)")
    except RuntimeError as e:
        if "set_wakeup_fd only works in main thread" in str(e):
            logger.error(f"Error in start method: {e}")
            logger.info("Starting ZeroMQ listener without signal handlers")
            if proxy:
                await proxy.zmq_listener()
        else:
            logger.error(f"Runtime error: {e}")
            raise
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Server error: {e}\n{error_details}")
        raise
    finally:
        if proxy:
            try:
                await proxy.stop()
            except Exception as cleanup_error:
                logger.error(f"Error during cleanup: {cleanup_error}")

if __name__ == "__main__":
    aio.run(main())