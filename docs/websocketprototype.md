# OpenAlgo WebSocket Implementation Guide

This document provides implementation details for the WebSocket proxy system described in [websocket.md](websocket.md).

## 1. Angel WebSocket Adapter

The Angel WebSocket Adapter connects to Angel's WebSocket API and forwards market data to the ZeroMQ message broker.

```python
# Angel WebSocket Adapter
class AngelWebSocketAdapter:
    def __init__(self):
        # ZeroMQ publisher setup
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.bind("tcp://*:5555")
        
        # Subscription tracking
        self.subscriptions = {}
        self.connected = False
        self.logger = logging.getLogger("angel_adapter")
        
    def initialize(self, user_id):
        # Get authentication tokens from database
        auth_token = get_auth_token(user_id)
        feed_token = get_feed_token(user_id)
        client_code = user_id  # Assuming user_id is the client code
        api_key = os.getenv('BROKER_API_KEY')
        
        # Create SmartWebSocketV2 instance
        self.sws = SmartWebSocketV2(
            auth_token, api_key, client_code, feed_token,
            max_retry_attempt=5
        )
        
        # Set callbacks
        self.sws.on_open = self.on_open
        self.sws.on_data = self.on_data
        self.sws.on_error = self.on_error
        self.sws.on_close = self.on_close
        
        # Start connection in a thread
        threading.Thread(target=self.sws.connect).start()
        
    def on_data(self, wsapp, message):
        try:
            # Process the message from Angel
            symbol = self.get_symbol_from_token(message["token"], message["exchange_type"])
            exchange = self.get_exchange_name(message["exchange_type"])
            
            # Format the data for clients
            data = {
                "symbol": symbol,
                "exchange": exchange,
                "ltp": message["last_traded_price"] / 100,
                "timestamp": message["exchange_timestamp"] / 1000,
                # Additional fields...
            }
            
            # Publish to ZeroMQ
            topic = f"{symbol}.{exchange}"
            self.socket.send_multipart([
                topic.encode('utf-8'),
                json.dumps(data).encode('utf-8')
            ])
            
        except Exception as e:
            self.logger.error(f"Error processing message: {e}")
    
    def subscribe(self, symbol, exchange, mode=2):  # mode 2 = QUOTE
        # Convert symbol and exchange to Angel format
        token = self.get_token_from_symbol(symbol, exchange)
        exchange_type = self.get_exchange_type(exchange)
        
        # Create token list for Angel API
        token_list = [{
            "exchangeType": exchange_type,
            "tokens": [token]
        }]
        
        # Generate a correlation ID
        correlation_id = f"{symbol}_{exchange}_{mode}"
        
        # Store subscription for reconnection
        self.subscriptions[correlation_id] = {
            "mode": mode,
            "tokens": token_list
        }
        
        # Subscribe if connected
        if self.connected:
            self.sws.subscribe(correlation_id, mode, token_list)
```

## 2. ZeroMQ Message Broker

The ZeroMQ layer provides efficient message distribution between components.

```python
# ZeroMQ Publisher
class ZeroMQPublisher:
    def __init__(self, bind_address="tcp://*:5555"):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.bind(bind_address)
        
    def publish(self, topic, message):
        self.socket.send_multipart([
            topic.encode('utf-8'),
            json.dumps(message).encode('utf-8')
        ])

# ZeroMQ Subscriber
class ZeroMQSubscriber:
    def __init__(self, connect_address="tcp://localhost:5555"):
        self.context = zmq.asyncio.Context()
        self.socket = self.context.socket(zmq.SUB)
        self.socket.connect(connect_address)
        self.callbacks = {}
        
    def subscribe(self, topic):
        self.socket.setsockopt_string(zmq.SUBSCRIBE, topic)
        
    async def listen(self, callback):
        while True:
            try:
                topic_bytes, data_bytes = await self.socket.recv_multipart()
                topic = topic_bytes.decode('utf-8')
                data = json.loads(data_bytes.decode('utf-8'))
                await callback(topic, data)
            except Exception as e:
                logging.error(f"Error in ZeroMQ listener: {e}")
                await asyncio.sleep(1)
```

## 3. WebSocket Proxy Server

The WebSocket Proxy Server provides a unified endpoint for clients to access market data.

```python
# WebSocket Proxy Server
class WebSocketProxy:
    def __init__(self, host="localhost", port=8765):
        self.host = host
        self.port = port
        self.clients = {}  # {client_id: {subscriptions: set(), websocket: WebSocketClientProtocol}}
        self.client_counter = 0
        self.zmq_subscriber = ZeroMQSubscriber()
        
    async def start(self):
        # Start ZeroMQ listener
        asyncio.create_task(self.zmq_subscriber.listen(self.on_market_data))
        
        # Start WebSocket server
        async with websockets.serve(
            self.handle_client, 
            self.host, 
            self.port,
            ping_interval=30,
            ping_timeout=10
        ):
            logging.info(f"WebSocket server started on ws://{self.host}:{self.port}")
            await asyncio.Future()  # Run forever
            
    async def on_market_data(self, topic, data):
        # Forward market data to subscribed clients
        await self.broadcast_to_subscribers(topic, data)
        
    async def handle_client(self, websocket, path):
        # Assign client ID
        client_id = self.client_counter
        self.client_counter += 1
        
        # Initialize client data
        self.clients[client_id] = {
            "subscriptions": set(),
            "websocket": websocket
        }
        
        try:
            # Process messages from client
            async for message in websocket:
                await self.process_client_message(client_id, message)
                
        except websockets.exceptions.ConnectionClosed:
            logging.info(f"Client {client_id} disconnected")
            
        finally:
            # Clean up client data
            if client_id in self.clients:
                del self.clients[client_id]
                
    async def process_client_message(self, client_id, message):
        try:
            data = json.loads(message)
            action = data.get("action")
            
            if action == "subscribe":
                symbol = data.get("symbol")
                exchange = data.get("exchange")
                
                if symbol and exchange:
                    # Add to client subscriptions
                    topic = f"{symbol}.{exchange}"
                    self.clients[client_id]["subscriptions"].add(topic)
                    
                    # Subscribe to ZeroMQ topic if needed
                    self.zmq_subscriber.subscribe(topic)
                    
                    # Notify client
                    await self.send_to_client(client_id, {
                        "type": "subscription",
                        "status": "success",
                        "symbol": symbol,
                        "exchange": exchange
                    })
                    
            elif action == "unsubscribe":
                symbol = data.get("symbol")
                exchange = data.get("exchange")
                
                if symbol and exchange:
                    topic = f"{symbol}.{exchange}"
                    if topic in self.clients[client_id]["subscriptions"]:
                        self.clients[client_id]["subscriptions"].remove(topic)
                        
                        # Notify client
                        await self.send_to_client(client_id, {
                            "type": "unsubscription",
                            "status": "success",
                            "symbol": symbol,
                            "exchange": exchange
                        })
                        
        except Exception as e:
            logging.error(f"Error processing client message: {e}")
            
    async def broadcast_to_subscribers(self, topic, data):
        for client_id, client_data in self.clients.items():
            if topic in client_data["subscriptions"]:
                await self.send_to_client(client_id, {
                    "type": "market_data",
                    "topic": topic,
                    "data": data
                })
                
    async def send_to_client(self, client_id, message):
        if client_id in self.clients:
            try:
                await self.clients[client_id]["websocket"].send(json.dumps(message))
            except websockets.exceptions.ConnectionClosed:
                logging.warning(f"Failed to send to client {client_id}, connection closed")
                if client_id in self.clients:
                    del self.clients[client_id]
```

## 4. Client Usage Example

### 4.1 JavaScript Client

```javascript
// Connect to WebSocket proxy
const socket = new WebSocket('ws://localhost:8765');

// Handle connection events
socket.onopen = function(e) {
  console.log('Connected to WebSocket proxy');
  
  // Subscribe to symbols
  subscribe('RELIANCE', 'NSE');
};

socket.onmessage = function(event) {
  const data = JSON.parse(event.data);
  
  if (data.type === 'market_data') {
    updateUI(data.data);
  } else if (data.type === 'subscription') {
    console.log(`Subscribed to ${data.symbol}.${data.exchange}`);
  }
};

// Subscribe to a symbol
function subscribe(symbol, exchange) {
  socket.send(JSON.stringify({
    action: 'subscribe',
    symbol: symbol,
    exchange: exchange
  }));
}

// Unsubscribe from a symbol
function unsubscribe(symbol, exchange) {
  socket.send(JSON.stringify({
    action: 'unsubscribe',
    symbol: symbol,
    exchange: exchange
  }));
}
```

### 4.2 Python Client

```python
import asyncio
import websockets
import json

async def connect_websocket():
    uri = "ws://localhost:8765"
    
    async with websockets.connect(uri) as websocket:
        # Subscribe to symbols
        await websocket.send(json.dumps({
            "action": "subscribe",
            "symbol": "RELIANCE",
            "exchange": "NSE"
        }))
        
        # Process incoming messages
        while True:
            message = await websocket.recv()
            data = json.loads(message)
            
            if data.get("type") == "market_data":
                print(f"Received market data: {data['data']}")

asyncio.run(connect_websocket())
```

## 5. Implementation Steps

1. Install required dependencies:
   ```
   pip install websockets zmq pyzmq asyncio
   ```

2. Create the Angel WebSocket Adapter module
3. Set up the ZeroMQ message broker
4. Implement the WebSocket Proxy Server
5. Test with sample clients
6. Add monitoring and logging
7. Deploy to production

## 6. Error Handling and Recovery

Implement these error handling strategies:

1. **Connection Failures**:
   - Automatic reconnection with exponential backoff
   - State tracking to prevent duplicate connections

2. **Message Processing Errors**:
   - Try-except blocks around message processing
   - Logging of errors without crashing the system

3. **Client Disconnections**:
   - Clean resource cleanup
   - Subscription state preservation

## 7. Testing

Test the system with these scenarios:

1. Normal operation with multiple clients
2. Broker disconnection and reconnection
3. Client disconnection and reconnection
4. High message volume handling
5. Error recovery scenarios
