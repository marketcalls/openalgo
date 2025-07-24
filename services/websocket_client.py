"""
Internal WebSocket client wrapper for connecting to the OpenAlgo WebSocket server.
This client handles authentication and provides a simple interface for services.
"""

import asyncio
import websockets
import json
import threading
import time
from typing import Dict, List, Any, Optional, Callable
from queue import Queue
import os
from dotenv import load_dotenv
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

class WebSocketClient:
    """
    Internal WebSocket client for connecting to OpenAlgo WebSocket server.
    Handles authentication, subscriptions, and data routing.
    """
    
    def __init__(self, api_key: str, host: str = "localhost", port: int = 8765):
        """
        Initialize the WebSocket client
        
        Args:
            api_key: API key for authentication
            host: WebSocket server host
            port: WebSocket server port
        """
        self.ws_url = f"ws://{host}:{port}"
        self.api_key = api_key
        self.ws = None
        self.loop = None
        self.thread = None
        self.connected = False
        self.authenticated = False
        self.running = False
        
        # Message handling
        self.message_queue = Queue()
        self.callbacks = {
            'market_data': [],
            'auth': [],
            'subscribe': [],
            'unsubscribe': [],
            'error': []
        }
        
        # Subscription tracking
        self.active_subscriptions = {}
        self.lock = threading.Lock()
        
        # Market data cache
        self.market_data_cache = {}
        
    def connect(self) -> bool:
        """
        Connect to the WebSocket server and authenticate
        
        Returns:
            bool: True if connected and authenticated successfully
        """
        if self.connected:
            logger.info("Already connected to WebSocket server")
            return True
            
        try:
            self.running = True
            
            # Start the asyncio event loop in a separate thread
            self.thread = threading.Thread(target=self._run_event_loop)
            self.thread.daemon = True
            self.thread.start()
            
            # Wait for connection
            timeout = 10
            start_time = time.time()
            while not self.connected and time.time() - start_time < timeout:
                time.sleep(0.1)
                
            if not self.connected:
                logger.error("Failed to connect to WebSocket server")
                return False
                
            # Wait for authentication
            start_time = time.time()
            while not self.authenticated and time.time() - start_time < timeout:
                time.sleep(0.1)
                
            if not self.authenticated:
                logger.error("Failed to authenticate with WebSocket server")
                return False
                
            logger.info("Successfully connected and authenticated")
            return True
            
        except Exception as e:
            logger.exception(f"Error connecting to WebSocket: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from the WebSocket server"""
        self.running = False
        
        if self.loop and self.ws:
            # Schedule the disconnect coroutine
            asyncio.run_coroutine_threadsafe(self._disconnect(), self.loop)
            
        # Wait for thread to finish
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
            
        self.connected = False
        self.authenticated = False
        logger.info("Disconnected from WebSocket server")
    
    def subscribe(self, symbols: List[Dict[str, str]], mode: str = "Quote") -> Dict[str, Any]:
        """
        Subscribe to market data for symbols
        
        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
            mode: Subscription mode - "LTP", "Quote", or "Depth"
            
        Returns:
            Dict with subscription status
        """
        if not self.connected or not self.authenticated:
            return {
                'status': 'error',
                'message': 'Not connected or authenticated'
            }
            
        try:
            subscription_msg = {
                "action": "subscribe",
                "symbols": symbols,
                "mode": mode
            }
            
            # Send subscription request
            if self.loop and self.ws:
                future = asyncio.run_coroutine_threadsafe(
                    self.ws.send(json.dumps(subscription_msg)), 
                    self.loop
                )
                future.result(timeout=5)
                
                # Track subscriptions
                with self.lock:
                    for symbol_info in symbols:
                        key = f"{symbol_info['exchange']}:{symbol_info['symbol']}"
                        if key not in self.active_subscriptions:
                            self.active_subscriptions[key] = set()
                        self.active_subscriptions[key].add(mode)
                
                return {
                    'status': 'success',
                    'message': f'Subscribed to {len(symbols)} symbols',
                    'symbols': symbols,
                    'mode': mode
                }
            else:
                return {
                    'status': 'error',
                    'message': 'WebSocket connection not available'
                }
                
        except Exception as e:
            logger.exception(f"Error subscribing to symbols: {e}")
            return {
                'status': 'error',
                'message': str(e)
            }
    
    def unsubscribe(self, symbols: List[Dict[str, str]], mode: str = "Quote") -> Dict[str, Any]:
        """
        Unsubscribe from market data
        
        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
            mode: Subscription mode - "LTP", "Quote", or "Depth"
            
        Returns:
            Dict with unsubscription status
        """
        if not self.connected or not self.authenticated:
            return {
                'status': 'error',
                'message': 'Not connected or authenticated'
            }
            
        try:
            unsubscription_msg = {
                "action": "unsubscribe",
                "symbols": symbols,
                "mode": mode
            }
            
            # Send unsubscription request
            if self.loop and self.ws:
                future = asyncio.run_coroutine_threadsafe(
                    self.ws.send(json.dumps(unsubscription_msg)), 
                    self.loop
                )
                future.result(timeout=5)
                
                # Update subscription tracking
                with self.lock:
                    for symbol_info in symbols:
                        key = f"{symbol_info['exchange']}:{symbol_info['symbol']}"
                        if key in self.active_subscriptions:
                            self.active_subscriptions[key].discard(mode)
                            if not self.active_subscriptions[key]:
                                del self.active_subscriptions[key]
                
                return {
                    'status': 'success',
                    'message': f'Unsubscribed from {len(symbols)} symbols',
                    'symbols': symbols,
                    'mode': mode
                }
            else:
                return {
                    'status': 'error',
                    'message': 'WebSocket connection not available'
                }
                
        except Exception as e:
            logger.exception(f"Error unsubscribing from symbols: {e}")
            return {
                'status': 'error',
                'message': str(e)
            }
    
    def unsubscribe_all(self) -> Dict[str, Any]:
        """Unsubscribe from all symbols"""
        if not self.connected or not self.authenticated:
            return {
                'status': 'error',
                'message': 'Not connected or authenticated'
            }
            
        try:
            unsubscription_msg = {
                "action": "unsubscribe_all"
            }
            
            # Send unsubscription request
            if self.loop and self.ws:
                future = asyncio.run_coroutine_threadsafe(
                    self.ws.send(json.dumps(unsubscription_msg)), 
                    self.loop
                )
                future.result(timeout=5)
                
                # Clear all subscriptions
                with self.lock:
                    self.active_subscriptions.clear()
                
                return {
                    'status': 'success',
                    'message': 'Unsubscribed from all symbols'
                }
            else:
                return {
                    'status': 'error',
                    'message': 'WebSocket connection not available'
                }
                
        except Exception as e:
            logger.exception(f"Error unsubscribing from all symbols: {e}")
            return {
                'status': 'error',
                'message': str(e)
            }
    
    def get_subscriptions(self) -> Dict[str, Any]:
        """Get current active subscriptions"""
        with self.lock:
            subscriptions = []
            for symbol_key, modes in self.active_subscriptions.items():
                exchange, symbol = symbol_key.split(':')
                for mode in modes:
                    subscriptions.append({
                        'exchange': exchange,
                        'symbol': symbol,
                        'mode': mode
                    })
            
            return {
                'status': 'success',
                'subscriptions': subscriptions,
                'count': len(subscriptions)
            }
    
    def get_market_data(self, symbol: Optional[str] = None, exchange: Optional[str] = None) -> Dict[str, Any]:
        """
        Get cached market data
        
        Args:
            symbol: Symbol to get data for (optional)
            exchange: Exchange to get data for (optional)
            
        Returns:
            Market data dictionary
        """
        with self.lock:
            if symbol and exchange:
                key = f"{exchange}:{symbol}"
                return self.market_data_cache.get(key, {})
            else:
                return dict(self.market_data_cache)
    
    def register_callback(self, event_type: str, callback: Callable):
        """
        Register a callback for specific event types
        
        Args:
            event_type: Type of event ('market_data', 'auth', 'subscribe', 'unsubscribe', 'error')
            callback: Function to call when event occurs
        """
        if event_type in self.callbacks:
            self.callbacks[event_type].append(callback)
            logger.info(f"Registered callback for {event_type} events")
    
    def unregister_callback(self, event_type: str, callback: Callable):
        """
        Unregister a callback
        
        Args:
            event_type: Type of event
            callback: Function to remove
        """
        if event_type in self.callbacks and callback in self.callbacks[event_type]:
            self.callbacks[event_type].remove(callback)
            logger.info(f"Unregistered callback for {event_type} events")
    
    def _run_event_loop(self):
        """Run the asyncio event loop in a separate thread"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        try:
            self.loop.run_until_complete(self._connect_and_run())
        except Exception as e:
            logger.exception(f"Error in event loop: {e}")
        finally:
            self.loop.close()
    
    async def _connect_and_run(self):
        """Connect to WebSocket and handle messages"""
        retry_count = 0
        max_retries = 5
        
        while self.running and retry_count < max_retries:
            try:
                async with websockets.connect(self.ws_url) as websocket:
                    self.ws = websocket
                    self.connected = True
                    logger.info(f"Connected to WebSocket server at {self.ws_url}")
                    
                    # Authenticate immediately after connection
                    await self._authenticate()
                    
                    # Handle messages
                    async for message in websocket:
                        if not self.running:
                            break
                        await self._handle_message(message)
                        
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"WebSocket connection closed: {e}")
                self.connected = False
                self.authenticated = False
                
                if self.running:
                    retry_count += 1
                    wait_time = min(2 ** retry_count, 30)  # Exponential backoff
                    logger.info(f"Reconnecting in {wait_time} seconds... (attempt {retry_count}/{max_retries})")
                    await asyncio.sleep(wait_time)
                    
            except Exception as e:
                logger.exception(f"Error in WebSocket connection: {e}")
                self.connected = False
                self.authenticated = False
                
                if self.running:
                    retry_count += 1
                    await asyncio.sleep(5)
    
    async def _authenticate(self):
        """Send authentication message"""
        auth_msg = {
            "action": "authenticate",
            "api_key": self.api_key
        }
        
        await self.ws.send(json.dumps(auth_msg))
        logger.info("Sent authentication request")
    
    async def _disconnect(self):
        """Disconnect from WebSocket"""
        if self.ws:
            await self.ws.close()
    
    async def _handle_message(self, message: str):
        """Handle incoming WebSocket messages"""
        try:
            data = json.loads(message)
            msg_type = data.get('type', data.get('status'))
            
            # Handle authentication response
            if msg_type == 'auth':
                if data.get('status') == 'success':
                    self.authenticated = True
                    logger.info("Authentication successful")
                else:
                    logger.error(f"Authentication failed: {data.get('message')}")
                    
                # Trigger auth callbacks
                for callback in self.callbacks['auth']:
                    try:
                        callback(data)
                    except Exception as e:
                        logger.error(f"Error in auth callback: {e}")
                        
            # Handle market data
            elif msg_type == 'market_data':
                symbol = data.get('symbol')
                exchange = data.get('exchange')
                
                if symbol and exchange:
                    # Cache the data
                    with self.lock:
                        key = f"{exchange}:{symbol}"
                        self.market_data_cache[key] = data
                    
                    # Trigger market data callbacks
                    for callback in self.callbacks['market_data']:
                        try:
                            callback(data)
                        except Exception as e:
                            logger.error(f"Error in market data callback: {e}")
                            
            # Handle subscription responses
            elif msg_type == 'subscribe':
                for callback in self.callbacks['subscribe']:
                    try:
                        callback(data)
                    except Exception as e:
                        logger.error(f"Error in subscribe callback: {e}")
                        
            # Handle unsubscription responses
            elif msg_type == 'unsubscribe':
                for callback in self.callbacks['unsubscribe']:
                    try:
                        callback(data)
                    except Exception as e:
                        logger.error(f"Error in unsubscribe callback: {e}")
                        
            # Handle errors
            elif data.get('status') == 'error':
                logger.error(f"Error from server: {data.get('message')}")
                for callback in self.callbacks['error']:
                    try:
                        callback(data)
                    except Exception as e:
                        logger.error(f"Error in error callback: {e}")
                        
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON message: {message}")
        except Exception as e:
            logger.exception(f"Error handling message: {e}")


# Singleton instance management
_client_instances = {}
_client_lock = threading.Lock()

def get_websocket_client(api_key: str, host: str = "localhost", port: int = 8765) -> WebSocketClient:
    """
    Get or create a WebSocket client instance for the given API key.
    Uses singleton pattern to reuse connections.
    
    Args:
        api_key: API key for authentication
        host: WebSocket server host
        port: WebSocket server port
        
    Returns:
        WebSocketClient instance
    """
    with _client_lock:
        if api_key not in _client_instances:
            client = WebSocketClient(api_key, host, port)
            if client.connect():
                _client_instances[api_key] = client
            else:
                raise ConnectionError("Failed to connect to WebSocket server")
        
        return _client_instances[api_key]

def close_all_clients():
    """Close all WebSocket client connections"""
    with _client_lock:
        for api_key, client in _client_instances.items():
            try:
                client.disconnect()
            except Exception as e:
                logger.error(f"Error closing client for API key {api_key}: {e}")
        _client_instances.clear()