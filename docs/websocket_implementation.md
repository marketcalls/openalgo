# WebSocket Adapter and Proxy Implementation

This document covers the WebSocket adapter and proxy implementation for the WebSocket streaming system. For the main architecture overview, see [websocket.md](websocket.md). For authentication and symbol mapping details, see [websocket_auth_and_mapping.md](websocket_auth_and_mapping.md).

> **Note**: The implementation includes cross-platform compatibility features with specific optimizations for Windows environments.

## 1. Broker WebSocket Adapter

The Broker WebSocket adapter provides a consistent interface to connect to any broker's WebSocket API. It handles data normalization and broadcasting in a broker-agnostic way, with broker-specific implementations.

### 1.1 Core Implementation

```python
# Broker WebSocket Adapter Base Class
import json
import threading
import zmq
import os
import logging
import importlib
import time
from abc import ABC, abstractmethod
from .mapping import SymbolMapper
from typing import Dict, Any, Optional, List

class BaseBrokerWebSocketAdapter(ABC):
    def __init__(self):
        # ZeroMQ publisher setup
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.bind("tcp://*:5555")
        
        # Subscription tracking
        self.subscriptions = {}
        self.connected = False
        self.logger = logging.getLogger("broker_adapter")
        
        # Connection management
        self.reconnect_delay = 5  # Initial delay in seconds
        self.max_reconnect_delay = 60  # Maximum delay in seconds
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.running = False
        self.lock = threading.Lock()
        
    @abstractmethod
    def initialize(self, broker_name, user_id, auth_data):
        """Initialize connection with broker WebSocket API
        
        Args:
            broker_name: The name of the broker (e.g., 'angel', 'zerodha')
            user_id: The user's ID or client code
            auth_data: Dict containing all required authentication data
        """
        pass
        
    @abstractmethod
    def subscribe(self, symbol, exchange, mode=2, depth_level=5):
        """Subscribe to market data with the specified mode and depth level"""
        pass
        
    @abstractmethod
    def unsubscribe(self, symbol, exchange, mode=2):
        """Unsubscribe from market data"""
        pass
        
    @abstractmethod
    def connect(self):
        """Establish connection to the broker's WebSocket"""
        pass
        
    @abstractmethod
    def disconnect(self):
        """Disconnect from the broker's WebSocket"""
        pass
        
    def on_open(self, wsapp):
        """Callback when connection is established"""
        self.logger.info("Connected to Angel WebSocket")
        self.connected = True
        
        # Resubscribe to existing subscriptions if reconnecting
        for correlation_id, sub in self.subscriptions.items():
            self.sws.subscribe(correlation_id, sub["mode"], sub["token_list"])
            
    def on_error(self, wsapp, error):
        """Callback for WebSocket errors"""
        self.logger.error(f"Angel WebSocket error: {error}")
        
    def on_close(self, wsapp):
        """Callback when connection is closed"""
        self.logger.info("Angel WebSocket connection closed")
        self.connected = False
```

### 1.2 Subscription Management

```python
def subscribe(self, symbol, exchange, mode=2, depth_level=5):
    """Subscribe to market data with specified mode and depth level"""
    try:
        # Map symbol to token
        token_info = self.symbol_mapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return {
                'status': 'error',
                'code': 'SYMBOL_NOT_FOUND',
                'message': f"Symbol {symbol} not found for exchange {exchange}"
            }
            
        token = token_info['token']
        brexchange = token_info['brexchange']
        
        # Check if the requested depth level is supported
        if mode == 4:  # Depth mode
            broker = "angel"  # Current broker
            supported_depths = BrokerCapabilityRegistry.get_supported_depth_levels(broker, exchange)
            
            if depth_level not in supported_depths:
                # If requested depth is not supported, use the highest available
                actual_depth = BrokerCapabilityRegistry.get_fallback_depth_level(
                    broker, exchange, depth_level
                )
                is_fallback = True
                
                self.logger.info(
                    f"Depth level {depth_level} not supported for {exchange}, "
                    f"using {actual_depth} instead"
                )
            else:
                actual_depth = depth_level
                is_fallback = False
                
            # Create subscription with appropriate depth level
            token_list = [{
                "exchangeType": ExchangeMapper.get_exchange_type(brexchange),
                "tokens": [token]
            }]
            
            # Generate correlation ID
            correlation_id = f"{symbol}_{exchange}_{mode}_{depth_level}"
            
            # Store subscription details for reconnection
            self.subscriptions[correlation_id] = {
                'symbol': symbol,
                'exchange': exchange,
                'brexchange': brexchange,
                'token': token,
                'mode': mode,
                'depth_level': depth_level,
                'actual_depth': actual_depth,
                'token_list': token_list,
                'is_fallback': is_fallback
            }
            
            # Subscribe if connected
            if self.connected:
                self.sws.subscribe(correlation_id, mode, token_list)
                
            return {
                'status': 'success',
                'symbol': symbol,
                'exchange': exchange,
                'mode': mode,
                'requested_depth': depth_level,
                'actual_depth': actual_depth,
                'is_fallback': is_fallback,
                'message': 'Subscription requested' if not is_fallback else 
                          f"Using depth level {actual_depth} instead of requested {depth_level}"
            }
        else:
            # For non-depth modes (LTP, QUOTE)
            token_list = [{
                "exchangeType": ExchangeMapper.get_exchange_type(brexchange),
                "tokens": [token]
            }]
            
            correlation_id = f"{symbol}_{exchange}_{mode}"
            
            # Store subscription
            self.subscriptions[correlation_id] = {
                'symbol': symbol,
                'exchange': exchange,
                'brexchange': brexchange,
                'token': token,
                'mode': mode,
                'token_list': token_list
            }
            
            # Subscribe if connected
            if self.connected:
                self.sws.subscribe(correlation_id, mode, token_list)
                
            return {
                'status': 'success',
                'symbol': symbol,
                'exchange': exchange,
                'mode': mode,
                'message': 'Subscription requested'
            }
            
    except Exception as e:
        self.logger.error(f"Error subscribing to {symbol}.{exchange}: {e}")
        return {
            'status': 'error',
            'code': 'SUBSCRIPTION_ERROR',
            'message': str(e)
        }

def unsubscribe(self, symbol, exchange, mode=2):
    """Unsubscribe from market data"""
    try:
        # Find correlation ID for the subscription
        correlation_id = None
        for sub_id, sub in self.subscriptions.items():
            if (sub['symbol'] == symbol and 
                sub['exchange'] == exchange and 
                sub['mode'] == mode):
                correlation_id = sub_id
                break
                
        if not correlation_id:
            return {
                'status': 'error',
                'code': 'NOT_SUBSCRIBED',
                'message': f"Not subscribed to {symbol}.{exchange} mode {mode}"
            }
            
        # Get the token list
        token_list = self.subscriptions[correlation_id]['token_list']
        
        # Unsubscribe if connected
        if self.connected:
            self.sws.unsubscribe(correlation_id, mode, token_list)
            
        # Remove from subscriptions
        del self.subscriptions[correlation_id]
        
        return {
            'status': 'success',
            'symbol': symbol,
            'exchange': exchange,
            'mode': mode,
            'message': 'Unsubscription successful'
        }
        
    except Exception as e:
        self.logger.error(f"Error unsubscribing from {symbol}.{exchange}: {e}")
        return {
            'status': 'error',
            'code': 'UNSUBSCRIPTION_ERROR',
            'message': str(e)
        }
```

### 1.3 Data Processing

```python
def on_data(self, wsapp, message):
    """Process market data from broker WebSocket
    
    This method handles broker-specific message formats and normalizes them
into a common format. Each broker adapter implements its own parsing logic.
    
    Note: Different brokers have different message formats and price scales.
    For example, Angel broker sends prices in paise (1/100th of a rupee),
    so we need to divide by 100 to get the actual price in rupees.
    """
    try:
        # Extract token and exchange type (example using Angel's format as reference)
        # Note: Each broker adapter will implement its own message parsing
        token = message.get('token')
        exchange_type = message.get('exchange_type')
        
        if not token or not exchange_type:
            return
            
        # Map broker-specific exchange type to standardized exchange code
        # This will be implemented differently for each broker
        brexchange = self.exchange_mapper.get_exchange_name(exchange_type, self.broker_name)
        
        # Convert token back to symbol
        symbol_info = self.symbol_mapper.get_symbol_from_token(token, brexchange)
        if not symbol_info:
            return
            
        symbol = symbol_info['symbol']
        exchange = symbol_info['exchange']
        
        # Find corresponding subscription to determine mode
        sub_info = None
        for sub_id, sub in self.subscriptions.items():
            if sub['token'] == token and sub['brexchange'] == brexchange:
                sub_info = sub
                break
                
        if not sub_info:
            return
            
        # Format data based on subscription mode
        mode = sub_info.get('mode', 2)  # Default to QUOTE mode
        
        # Common data for all modes
        formatted_data = {
            'symbol': symbol,
            'exchange': exchange,
            'ltp': message.get('last_traded_price', 0) / 100,
            'timestamp': message.get('exchange_timestamp', 0) / 1000
        }
        
        # Add mode-specific data
        if mode == 1:  # LTP mode - minimal data
            pass  # Already has the basic fields
            
        elif mode == 2:  # QUOTE mode - full quote
            formatted_data.update({
                'open': message.get('open_price_of_the_day', 0) / 100,
                'high': message.get('high_price_of_the_day', 0) / 100,
                'low': message.get('low_price_of_the_day', 0) / 100,
                'close': message.get('closed_price', 0) / 100,
                'volume': message.get('volume_trade_for_the_day', 0),
                'last_trade_quantity': message.get('last_traded_quantity', 0),
                'avg_trade_price': message.get('average_trade_price', 0) / 100
            })
            
        elif mode == 4:  # DEPTH mode
            # Extract depth data
            depth_data = message.get('depth', {})
            
            # Get the requested and actual depth levels
            requested_depth = sub_info.get('depth_level', 5)
            actual_depth = sub_info.get('actual_depth', 5)
            is_fallback = sub_info.get('is_fallback', False)
            
            # Format buy and sell depth
            formatted_depth = {
                'buy': [],
                'sell': []
            }
            
            # Process buy depth
            buy_depth = depth_data.get('buy', [])
            for i, level in enumerate(buy_depth):
                if i >= actual_depth:
                    break
                formatted_depth['buy'].append({
                    'price': level.get('price', 0) / 100,
                    'quantity': level.get('quantity', 0),
                    'orders': level.get('orders', 0)
                })
                
            # Process sell depth
            sell_depth = depth_data.get('sell', [])
            for i, level in enumerate(sell_depth):
                if i >= actual_depth:
                    break
                formatted_depth['sell'].append({
                    'price': level.get('price', 0) / 100,
                    'quantity': level.get('quantity', 0),
                    'orders': level.get('orders', 0)
                })
                
            # Add depth to formatted data
            formatted_data['depth'] = formatted_depth
            
            # Add broker support information
            formatted_data['broker_supported'] = not is_fallback
            if is_fallback:
                formatted_data['broker_message'] = (
                    f"Angel broker only supports up to {actual_depth} depth "
                    f"levels for {exchange}"
                )
                
        # Create final message
        market_data = {
            'type': 'market_data',
            'mode': mode,
            'topic': f"{symbol}.{exchange}",
            'data': formatted_data
        }
        
        # Add depth-specific fields
        if mode == 4:
            market_data['depth_level'] = sub_info.get('depth_level', 5)
            if sub_info.get('is_fallback', False):
                market_data['actual_depth_level'] = sub_info.get('actual_depth', 5)
                
        # Publish to ZeroMQ
        topic = f"{symbol}.{exchange}.{mode}"
        self.socket.send_multipart([
            topic.encode('utf-8'),
            json.dumps(market_data).encode('utf-8')
        ])
            
    except Exception as e:
        self.logger.error(f"Error processing message: {e}")
```

## 2. WebSocket Proxy Server

The WebSocket proxy server handles client connections, API key validation, and manages subscriptions with support for all depth levels. The implementation includes cross-platform compatibility and Windows-specific optimizations.

### 2.1 Core Implementation

```python
# WebSocket Proxy Server
import asyncio
import websockets
import json
import zmq.asyncio
import logging
from websocket_auth_and_mapping import AuthService

class WebSocketProxy:
    def __init__(self, host="localhost", port=8765):
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
        # Start ZeroMQ listener
        asyncio.create_task(self.zmq_listener())
        
        # Start WebSocket server
        async with websockets.serve(
            self.handle_client, 
            self.host, 
            self.port,
            ping_interval=30,
            ping_timeout=10
        ):
            self.logger.info(f"WebSocket server started on ws://{self.host}:{self.port}")
            await asyncio.Future()  # Run forever
```

### 2.2 Client Connection Handling

```python
async def handle_client(self, websocket, path):
    """Handle a new client connection"""
    # Assign client ID
    client_id = self.client_counter
    self.client_counter += 1
    
    # Initialize client data
    self.clients[client_id] = {
        "auth": None,
        "subscriptions": set(),
        "websocket": websocket
    }
    
    self.logger.info(f"Client {client_id} connected")
    
    try:
        # First message must be authentication
        auth_message = await websocket.recv()
        auth_data = json.loads(auth_message)
        
        if auth_data.get('action') != 'authenticate' or not auth_data.get('api_key'):
            await websocket.send(json.dumps({
                "type": "error",
                "code": "AUTHENTICATION_REQUIRED",
                "message": "First message must be authentication with API key"
            }))
            del self.clients[client_id]
            return
            
        # Validate API key
        api_key = auth_data.get('api_key')
        auth_result = self.auth_service.validate_api_key(api_key)
        
        if not auth_result:
            await websocket.send(json.dumps({
                "type": "error",
                "code": "INVALID_API_KEY",
                "message": "Invalid API key"
            }))
            del self.clients[client_id]
            return
            
        # Store authentication data
        self.clients[client_id]["auth"] = auth_result
        
        # Send successful authentication response
        await websocket.send(json.dumps({
            "type": "authentication",
            "status": "success",
            "message": "Authentication successful"
        }))
        
        # Process subsequent messages
        async for message in websocket:
            await self.process_client_message(client_id, message)
            
    except websockets.exceptions.ConnectionClosed:
        self.logger.info(f"Client {client_id} disconnected")
        
    except Exception as e:
        self.logger.error(f"Error handling client {client_id}: {e}")
        
    finally:
        # Clean up client data
        if client_id in self.clients:
            del self.clients[client_id]
```

### 2.3 Message Processing

```python
async def process_client_message(self, client_id, message):
    """Process subscription and unsubscription messages"""
    try:
        data = json.loads(message)
        action = data.get("action")
        
        if action == "subscribe":
            # Extract subscription parameters
            symbol = data.get("symbol")
            exchange = data.get("exchange")
            mode = data.get("mode", 2)  # Default to QUOTE mode
            depth_level = data.get("depth_level", 5)  # Default to 5 levels
            
            if not symbol or not exchange:
                await self.send_to_client(client_id, {
                    "type": "error",
                    "code": "INVALID_PARAMETERS",
                    "message": "Symbol and exchange are required"
                })
                return
                
            # Validate mode
            if mode not in [1, 2, 4]:
                await self.send_to_client(client_id, {
                    "type": "error",
                    "code": "INVALID_MODE",
                    "message": "Mode must be 1 (LTP), 2 (QUOTE), or 4 (DEPTH)"
                })
                return
                
            # For depth mode, validate depth level
            if mode == 4 and depth_level not in [5, 20, 30, 50]:
                await self.send_to_client(client_id, {
                    "type": "error",
                    "code": "INVALID_DEPTH_LEVEL",
                    "message": "Depth level must be 5, 20, 30, or 50"
                })
                return
                
            # Get authentication data
            auth_data = self.clients[client_id]["auth"]
            if not auth_data:
                await self.send_to_client(client_id, {
                    "type": "error",
                    "code": "NOT_AUTHENTICATED",
                    "message": "Client not authenticated"
                })
                return
                
            # Subscribe to market data
            topic = f"{symbol}.{exchange}.{mode}"
            self.clients[client_id]["subscriptions"].add(topic)
            
            # Subscribe to ZeroMQ topic
            self.socket.setsockopt_string(zmq.SUBSCRIBE, topic)
            
            # Send confirmation to client
            await self.send_to_client(client_id, {
                "type": "subscription",
                "status": "success",
                "symbol": symbol,
                "exchange": exchange,
                "mode": mode,
                "depth_level": depth_level if mode == 4 else None
            })
            
        elif action == "unsubscribe":
            # Extract parameters
            symbol = data.get("symbol")
            exchange = data.get("exchange")
            mode = data.get("mode", 2)
            
            if not symbol or not exchange:
                await self.send_to_client(client_id, {
                    "type": "error",
                    "code": "INVALID_PARAMETERS",
                    "message": "Symbol and exchange are required"
                })
                return
                
            # Remove subscription
            topic = f"{symbol}.{exchange}.{mode}"
            if topic in self.clients[client_id]["subscriptions"]:
                self.clients[client_id]["subscriptions"].remove(topic)
                
                # Send confirmation to client
                await self.send_to_client(client_id, {
                    "type": "unsubscription",
                    "status": "success",
                    "symbol": symbol,
                    "exchange": exchange,
                    "mode": mode
                })
            else:
                await self.send_to_client(client_id, {
                    "type": "error",
                    "code": "NOT_SUBSCRIBED",
                    "message": f"Not subscribed to {symbol}.{exchange} mode {mode}"
                })
                
        else:
            await self.send_to_client(client_id, {
                "type": "error",
                "code": "INVALID_ACTION",
                "message": f"Invalid action: {action}"
            })
            
    except json.JSONDecodeError:
        await self.send_to_client(client_id, {
            "type": "error",
            "code": "INVALID_JSON",
            "message": "Invalid JSON message"
        })
        
    except Exception as e:
        await self.send_to_client(client_id, {
            "type": "error",
            "code": "INTERNAL_ERROR",
            "message": str(e)
        })
```

### 2.4 Data Forwarding

```python
async def zmq_listener(self):
    """Listen for messages from ZeroMQ and forward to clients"""
    while True:
        try:
            # Receive message from ZeroMQ
            topic_bytes, data_bytes = await self.socket.recv_multipart()
            topic = topic_bytes.decode('utf-8')
            data = json.loads(data_bytes.decode('utf-8'))
            
            # Forward to subscribed clients
            await self.broadcast_to_subscribers(topic, data)
            
        except Exception as e:
            self.logger.error(f"Error in ZeroMQ listener: {e}")
            await asyncio.sleep(1)  # Prevent tight loop on error
            
async def broadcast_to_subscribers(self, topic, data):
    """Forward market data to subscribed clients"""
    for client_id, client_info in list(self.clients.items()):
        if topic in client_info["subscriptions"]:
            try:
                await self.send_to_client(client_id, data)
            except Exception as e:
                self.logger.error(f"Error sending to client {client_id}: {e}")
                
async def send_to_client(self, client_id, data):
    """Send data to a specific client"""
    if client_id in self.clients:
        try:
            await self.clients[client_id]["websocket"].send(json.dumps(data))
        except websockets.exceptions.ConnectionClosed:
            self.logger.warning(f"Connection closed for client {client_id}")
            if client_id in self.clients:
                del self.clients[client_id]
```

## 3. Implementation for Depth 50 and Broker Limitations

### 3.1 Handling Different Depth Levels

When working with various depth levels (5/20/30/50), the system needs to:

1. Check if the requested depth level is supported by the broker
2. Fall back to the highest available depth level if not supported
3. Inform the client about the limitation

```python
# In the AngelWebSocketAdapter class:
def handle_depth_subscription(self, broker, symbol, exchange, depth_level=5):
    """Handle subscription with proper depth level support"""
    # Get current broker name
    
    # Check supported depths
    supported_depths = BrokerCapabilityRegistry.get_supported_depth_levels(broker, exchange)
    
    if depth_level not in supported_depths:
        # Fall back to highest available depth
        actual_depth = BrokerCapabilityRegistry.get_fallback_depth_level(
            broker, exchange, depth_level
        )
        
        self.logger.info(
            f"Requested depth level {depth_level} not supported for {exchange} on {broker}. "
            f"Using {actual_depth} instead."
        )
        
        return {
            'depth_level': depth_level,
            'actual_depth': actual_depth,
            'is_fallback': True,
            'message': f"Depth level {depth_level} not supported, using {actual_depth}"
        }
    
    return {
        'depth_level': depth_level,
        'actual_depth': depth_level,
        'is_fallback': False,
        'message': f"Using requested depth level {depth_level}"
    }
```

### 3.2 Broker-Specific Error Responses

The system should provide clear error messages when a broker doesn't support a feature:

```python
def create_broker_limitation_response(broker, exchange, feature, supported_values=None):
    """Create standard error response for broker limitations"""
    message = f"Feature '{feature}' is not supported by broker {broker} for exchange {exchange}"
    
    response = {
        "type": "error",
        "code": "BROKER_LIMITATION",
        "message": message,
        "broker": broker,
        "exchange": exchange,
        "feature": feature
    }
    
    if supported_values:
        response["supported_values"] = supported_values
        
    return response
```

## 4. Running the WebSocket System

### 4.1 Main Entry Point

```python
# main.py
import asyncio
import logging
from broker_factory import create_broker_adapter
from websocket_proxy import WebSocketProxy
from websocket_auth_and_mapping import initialize_services, get_user_broker

async def main():
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Set platform-specific event loop policy for Windows
    if platform.system() == 'Windows':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        logger.info("Set Windows-specific event loop policy")
    
    # Initialize server with port checking
    host = "localhost"
    port = 8765
    
    # Check if port is in use and find alternative if needed
    if is_port_in_use(host, port):
        available_port = find_available_port(port + 1)
        if available_port:
            logger.info(f"Port {port} is in use, using port {available_port} instead")
            port = available_port
        else:
            logger.warning(f"Could not find an available port, using {port} anyway")
    
    # Initialize services
    auth_service, symbol_mapper = initialize_services()
    
    # Get the user's active broker from the database
    user_data = auth_service.get_current_user()
    active_broker = user_data.get('active_broker')
    
    # Create the appropriate broker adapter
    adapter = create_broker_adapter(active_broker)
    
    # Initialize the adapter with user's authentication data
    adapter.initialize(
        broker_name=active_broker,
        user_id=user_data.get('user_id'),
        auth_data={
            'auth_token': user_data.get('auth_token'),
            'feed_token': user_data.get('feed_token'),
            'api_key': os.getenv('BROKER_API_KEY'),
            # Other broker-specific auth data
        }
    )
    
    # Create proxy instance
    proxy = WebSocketProxy(host="0.0.0.0", port=8765)
    
    # Start the proxy server
    await proxy.start()

if __name__ == "__main__":
    asyncio.run(main())
```

## 5. Implementation Recommendations

1. **Component Separation**: 
   - Keep the adapter and proxy components separate for better maintainability
   - Use dependency injection for services like authentication and symbol mapping

2. **Error Handling**:
   - Implement comprehensive error handling at all levels
   - Provide clear error messages with broker-specific information when applicable

3. **Performance Optimization**:
   - Use caching for symbol mapping and token lookups
   - Implement message compression for large market depth data
   - Consider sharding for high-volume symbols

4. **Testing**:
   - Create mock versions of the Angel WebSocket for testing
   - Implement stress tests for handling multiple depth subscriptions
   - Test failover and reconnection scenarios

5. **Monitoring**:
   - Log all WebSocket events for troubleshooting
   - Implement metrics for tracking subscription counts and message rates
   - Monitor broker limitations and fallbacks

This implementation guide provides the core components needed to implement the WebSocket proxy system with support for all depth levels (5/20/30/50) and proper handling of broker limitations.
