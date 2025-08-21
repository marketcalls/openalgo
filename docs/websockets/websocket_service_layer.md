# WebSocket Service Layer Documentation

## Overview

The WebSocket Service Layer provides a clean separation between external API consumption (with authentication) and internal application usage (without authentication overhead). This modular architecture follows the same pattern as the existing `restx_api/` and `services/` structure.

## Architecture Diagram

```
┌─────────────────────┐    ┌──────────────────────┐    ┌─────────────────────┐
│   External SDKs     │    │   Internal Flask     │    │   WebSocket Proxy   │
│   (Python/JS)      │    │   Application        │    │   Server             │
├─────────────────────┤    ├──────────────────────┤    ├─────────────────────┤
│ - API Key Required  │    │ - Session Based      │    │ - Broker Adapters   │
│ - Direct Connection │    │ - Service Layer      │    │ - ZeroMQ Publisher  │
│ - Full Features     │    │ - No Auth Overhead   │    │ - Real-time Stream  │
└─────────────────────┘    └──────────────────────┘    └─────────────────────┘
           │                           │                           │
           └───────────────────────────┼───────────────────────────┘
                                       │
                               ┌───────────────┐
                               │   Service     │
                               │   Layer       │
                               │   Interface   │
                               └───────────────┘
```

## Design Principles

### 1. Separation of Concerns
- **External Access**: Direct WebSocket connection with API key authentication
- **Internal Access**: Service layer functions without authentication overhead
- **Single Data Source**: One WebSocket server serves both use cases

### 2. Authentication Strategy
- **External**: API key validation for Python SDKs and external applications
- **Internal**: Session-based authentication for Flask UI components
- **No Duplication**: Same data stream, different access patterns

### 3. Performance Optimization
- **Direct Streaming**: No intermediate layers for external clients
- **Cached Access**: Service layer provides cached data for internal use
- **Minimal Latency**: Sub-millisecond updates for trading applications

## File Structure

```
services/
├── websocket_client.py      # Internal WebSocket client wrapper
├── websocket_service.py     # Service layer functions  
└── market_data_service.py   # Market data caching and broadcasting

blueprints/
└── websocket_example.py     # Flask blueprint for UI integration

websocket_proxy/
├── server.py               # Main WebSocket proxy server
├── broker_factory.py       # Dynamic broker adapter creation
└── base_adapter.py         # Base class for broker adapters
```

## Service Layer Components

### 1. WebSocket Client (`websocket_client.py`)

**Purpose**: Internal wrapper for connecting to the WebSocket proxy server.

#### Key Features
- **Connection Management**: Automatic connection and authentication
- **Thread Safety**: Handles async operations in separate threads
- **Message Routing**: Routes market data to registered callbacks
- **Reconnection Logic**: Automatic reconnection with exponential backoff
- **Subscription Tracking**: Maintains active subscription state

#### Usage Example
```python
from services.websocket_client import get_websocket_client

# Get authenticated client instance
client = get_websocket_client(api_key, host="localhost", port=8765)

# Subscribe to market data
result = client.subscribe([
    {'symbol': 'RELIANCE', 'exchange': 'NSE'}
], mode='Quote')

# Register callback for updates
def market_callback(data):
    print(f"Received: {data['symbol']} @ {data['data']['ltp']}")

client.register_callback('market_data', market_callback)
```

#### Class Methods
```python
class WebSocketClient:
    def __init__(self, api_key: str, host: str = "localhost", port: int = 8765)
    def connect(self) -> bool
    def disconnect(self)
    def subscribe(self, symbols: List[Dict], mode: str = "Quote") -> Dict
    def unsubscribe(self, symbols: List[Dict], mode: str = "Quote") -> Dict
    def unsubscribe_all(self) -> Dict
    def get_subscriptions(self) -> Dict
    def get_market_data(self, symbol: str = None, exchange: str = None) -> Dict
    def register_callback(self, event_type: str, callback: Callable)
    def unregister_callback(self, event_type: str, callback: Callable)
```

### 2. WebSocket Service (`websocket_service.py`)

**Purpose**: High-level service functions for internal Flask application use.

#### Key Features
- **Session Integration**: Uses Flask session for user identification
- **API Key Management**: Automatically retrieves user API keys
- **Error Handling**: Comprehensive error handling and logging
- **Type Safety**: Full type hints and return type specifications
- **Caching**: Efficient data retrieval and caching

#### Core Functions

##### Connection Management
```python
def get_websocket_connection(username: str) -> Tuple[bool, Optional[WebSocketClient], Optional[str]]:
    """
    Get or create a WebSocket connection for a user
    
    Returns:
        Tuple of (success, client, error_message)
    """
```

##### Status and Information
```python
def get_websocket_status(username: str, broker: Optional[str] = None) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get WebSocket connection status for a user
    
    Returns:
        Tuple of (success, response_data, status_code)
    """

def get_websocket_subscriptions(username: str, broker: Optional[str] = None) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get current WebSocket subscriptions for a user
    
    Returns:
        Tuple of (success, response_data, status_code)  
    """
```

##### Subscription Management
```python
def subscribe_to_symbols(username: str, broker: str, symbols: List[Dict[str, str]], mode: str = "Quote") -> Tuple[bool, Dict[str, Any], int]:
    """
    Subscribe to market data for symbols
    
    Args:
        username: Username
        broker: Broker name
        symbols: List of symbol dictionaries with 'symbol' and 'exchange' keys
        mode: Subscription mode ("LTP", "Quote", or "Depth")
    
    Returns:
        Tuple of (success, response_data, status_code)
    """

def unsubscribe_from_symbols(username: str, broker: str, symbols: List[Dict[str, str]], mode: str = "Quote") -> Tuple[bool, Dict[str, Any], int]:
    """Unsubscribe from market data for symbols"""

def unsubscribe_all(username: str, broker: str) -> Tuple[bool, Dict[str, Any], int]:
    """Unsubscribe from all market data"""
```

##### Data Access
```python
def get_market_data(username: str, symbol: Optional[str] = None, exchange: Optional[str] = None) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get cached market data from WebSocket client
    
    Returns:
        Tuple of (success, response_data, status_code)
    """
```

#### Response Format
All service functions return consistent response format:

**Success Response:**
```python
(True, {
    'status': 'success',
    'data': {...},
    'message': 'Operation completed successfully'
}, 200)
```

**Error Response:**
```python
(False, {
    'status': 'error', 
    'message': 'Detailed error description',
    'error_code': 'SPECIFIC_ERROR_CODE'
}, 400)
```

### 3. Market Data Service (`market_data_service.py`)

**Purpose**: Advanced market data caching, transformation, and broadcasting.

#### Key Features
- **Singleton Pattern**: Single instance manages all market data
- **Thread-Safe Caching**: Concurrent access support
- **Data Transformation**: Standardizes data from different brokers
- **Subscription Broadcasting**: Notifies multiple subscribers
- **Performance Metrics**: Cache hit rates and update statistics
- **Automatic Cleanup**: Removes stale data and subscriptions

#### Core Functionality

##### Data Processing
```python
class MarketDataService:
    def process_market_data(self, data: Dict[str, Any]) -> None:
        """Process incoming market data from WebSocket"""
    
    def get_ltp(self, symbol: str, exchange: str) -> Optional[Dict[str, Any]]:
        """Get latest LTP for a symbol"""
    
    def get_quote(self, symbol: str, exchange: str) -> Optional[Dict[str, Any]]:
        """Get latest quote for a symbol"""
    
    def get_market_depth(self, symbol: str, exchange: str) -> Optional[Dict[str, Any]]:
        """Get market depth for a symbol"""
    
    def get_multiple_ltps(self, symbols: List[Dict[str, str]]) -> Dict[str, Any]:
        """Get LTPs for multiple symbols"""
```

##### Subscription Management
```python
    def subscribe_to_updates(self, event_type: str, callback: Callable, filter_symbols: Optional[Set[str]] = None) -> int:
        """Subscribe to market data updates"""
    
    def unsubscribe_from_updates(self, subscriber_id: int) -> bool:
        """Unsubscribe from market data updates"""
```

##### Performance Monitoring
```python
    def get_cache_metrics(self) -> Dict[str, Any]:
        """Get performance metrics"""
        # Returns:
        # {
        #     'total_symbols': 150,
        #     'total_updates': 45231,
        #     'cache_hits': 1834,
        #     'cache_misses': 23,
        #     'hit_rate': 98.75,
        #     'total_subscribers': 5
        # }
```

#### Cache Structure
```python
# Market data cache format
{
    'NSE:RELIANCE': {
        'ltp': {'value': 1402.7, 'timestamp': 1753340515071},
        'quote': {
            'open': 1419.2, 'high': 1423.0, 'low': 1396.0, 'close': 1424.6,
            'ltp': 1402.7, 'volume': 7082847, 'timestamp': 1753340515071
        },
        'depth': {
            'buy': [{'price': 1402.5, 'quantity': 674, 'orders': 6}, ...],
            'sell': [{'price': 1402.7, 'quantity': 696, 'orders': 4}, ...],
            'timestamp': 1753340515071
        },
        'last_update': 1753340515071
    }
}
```

## Flask Integration

### Blueprint Structure (`websocket_example.py`)

**Purpose**: Provides REST API endpoints for WebSocket functionality within Flask application.

#### REST Endpoints

##### Status and Information
```python
@websocket_bp.route('/api/websocket/status', methods=['GET'])
def api_websocket_status():
    """Get WebSocket connection status for current user"""

@websocket_bp.route('/api/websocket/subscriptions', methods=['GET']) 
def api_websocket_subscriptions():
    """Get current subscriptions for current user"""

@websocket_bp.route('/api/websocket/apikey', methods=['GET'])
def api_get_websocket_apikey():
    """Get API key for WebSocket authentication"""
```

##### Subscription Management
```python
@websocket_bp.route('/api/websocket/subscribe', methods=['POST'])
def api_websocket_subscribe():
    """Subscribe to symbols for current user"""

@websocket_bp.route('/api/websocket/unsubscribe', methods=['POST'])
def api_websocket_unsubscribe():
    """Unsubscribe from symbols for current user"""

@websocket_bp.route('/api/websocket/unsubscribe-all', methods=['POST'])
def api_websocket_unsubscribe_all():
    """Unsubscribe from all symbols for current user"""
```

##### Data Access
```python
@websocket_bp.route('/api/websocket/market-data', methods=['GET'])
def api_websocket_market_data():
    """Get cached market data"""
```

#### Session Management
```python
def get_username_from_session():
    """Get username from current session"""
    username = session.get('user')
    if username:
        # Verify API key exists
        from database.auth_db import get_api_key_for_tradingview
        api_key = get_api_key_for_tradingview(username)
        return username if api_key else None
    return None
```

## External SDK Integration

### Python SDK Example

```python
import websockets
import json
import asyncio

class OpenAlgoWebSocket:
    def __init__(self, api_key):
        self.api_key = api_key
        self.ws_url = "ws://localhost:8765"
        self.websocket = None
        
    async def connect(self):
        """Connect and authenticate"""
        self.websocket = await websockets.connect(self.ws_url)
        
        # Authenticate
        auth_msg = {
            "action": "authenticate",
            "api_key": self.api_key
        }
        await self.websocket.send(json.dumps(auth_msg))
        
        # Wait for auth response
        response = await self.websocket.recv()
        auth_data = json.loads(response)
        
        if auth_data.get("status") != "success":
            raise Exception(f"Authentication failed: {auth_data.get('message')}")
            
    async def subscribe(self, symbols, mode="Quote"):
        """Subscribe to market data"""
        message = {
            "action": "subscribe",
            "symbols": symbols,
            "mode": mode
        }
        await self.websocket.send(json.dumps(message))
        
    async def listen(self, callback):
        """Listen for market data updates"""
        async for message in self.websocket:
            data = json.loads(message)
            if data.get("type") == "market_data":
                await callback(data)

# Usage
async def market_callback(data):
    print(f"Market Update: {data['symbol']} = ₹{data['data']['ltp']}")

async def main():
    client = OpenAlgoWebSocket("your_api_key_here")
    await client.connect()
    
    await client.subscribe([
        {"symbol": "RELIANCE", "exchange": "NSE"},
        {"symbol": "TCS", "exchange": "NSE"}
    ], mode="LTP")
    
    await client.listen(market_callback)

# Run
asyncio.run(main())
```

### JavaScript SDK Example

```javascript
class OpenAlgoWebSocket {
    constructor(apiKey) {
        this.apiKey = apiKey;
        this.wsUrl = 'ws://localhost:8765';
        this.socket = null;
        this.callbacks = {};
    }
    
    connect() {
        return new Promise((resolve, reject) => {
            this.socket = new WebSocket(this.wsUrl);
            
            this.socket.onopen = () => {
                // Authenticate
                this.socket.send(JSON.stringify({
                    action: 'authenticate',
                    api_key: this.apiKey
                }));
            };
            
            this.socket.onmessage = (event) => {
                const data = JSON.parse(event.data);
                
                if (data.type === 'auth') {
                    if (data.status === 'success') {
                        resolve();
                    } else {
                        reject(new Error(data.message));
                    }
                } else if (data.type === 'market_data') {
                    this.callbacks.marketData?.(data);
                }
            };
            
            this.socket.onerror = (error) => reject(error);
        });
    }
    
    subscribe(symbols, mode = 'Quote') {
        this.socket.send(JSON.stringify({
            action: 'subscribe',
            symbols: symbols,
            mode: mode
        }));
    }
    
    onMarketData(callback) {
        this.callbacks.marketData = callback;
    }
}

// Usage
const client = new OpenAlgoWebSocket('your_api_key_here');

client.connect().then(() => {
    console.log('Connected to OpenAlgo WebSocket');
    
    client.onMarketData((data) => {
        console.log(`${data.symbol}: ₹${data.data.ltp}`);
    });
    
    client.subscribe([
        {symbol: 'RELIANCE', exchange: 'NSE'},
        {symbol: 'TCS', exchange: 'NSE'}
    ], 'LTP');
});
```

## Configuration

### Environment Variables

```bash
# WebSocket Server Configuration
WEBSOCKET_HOST='localhost'
WEBSOCKET_PORT='8765'
WEBSOCKET_URL='ws://localhost:8765'

# ZeroMQ Configuration  
ZMQ_HOST='localhost'
ZMQ_PORT='5555'

# API Key Configuration
API_KEY_PEPPER='your_pepper_here'
```

### Service Configuration

```python
# services/websocket_service.py
WS_HOST = os.getenv('WEBSOCKET_HOST', '127.0.0.1')
WS_PORT = int(os.getenv('WEBSOCKET_PORT', '8765'))

# Connection timeout settings
CONNECTION_TIMEOUT = 10  # seconds
AUTHENTICATION_TIMEOUT = 5  # seconds
RECONNECTION_MAX_ATTEMPTS = 5
RECONNECTION_DELAY = 1  # seconds (exponential backoff)
```

## Error Handling

### Service Layer Errors

#### Connection Errors
```python
# Connection timeout
(False, {
    'status': 'error',
    'message': 'WebSocket connection timeout after 10 seconds',
    'error_code': 'CONNECTION_TIMEOUT'
}, 503)

# Authentication failure
(False, {
    'status': 'error', 
    'message': 'Invalid API key or authentication failed',
    'error_code': 'AUTH_FAILED'
}, 401)
```

#### Subscription Errors
```python
# Invalid symbols
(False, {
    'status': 'error',
    'message': 'No symbols provided for subscription',
    'error_code': 'INVALID_SYMBOLS'
}, 400)

# Broker adapter error
(False, {
    'status': 'error',
    'message': 'Broker adapter not available for user',
    'error_code': 'BROKER_UNAVAILABLE'  
}, 503)
```

### Client Error Handling

```python
# websocket_client.py
try:
    success, client, error = get_websocket_connection(username)
    if not success:
        logger.error(f"Connection failed: {error}")
        return False, {'status': 'error', 'message': error}, 503
        
except ConnectionError as e:
    logger.error(f"Network error: {e}")
    return False, {'status': 'error', 'message': 'Network connection failed'}, 503
    
except Exception as e:
    logger.exception(f"Unexpected error: {e}")
    return False, {'status': 'error', 'message': 'Internal server error'}, 500
```

## Performance Considerations

### Connection Pooling
- **Singleton Pattern**: Reuses WebSocket connections per API key
- **Thread Safety**: Concurrent access with proper locking
- **Resource Management**: Automatic cleanup of idle connections

### Data Caching
- **TTL Cache**: 5-minute cache for authentication tokens
- **Market Data Cache**: Real-time updates with stale data cleanup
- **Memory Efficiency**: Automatic removal of old data

### Scalability
- **Horizontal Scaling**: Multiple WebSocket proxy instances
- **Load Balancing**: Round-robin connection distribution
- **Resource Monitoring**: Memory and connection usage tracking

## Security Considerations

### Authentication
- **API Key Validation**: Argon2 hashing with pepper
- **Session Management**: Flask session integration
- **Token Expiration**: Time-based token invalidation

### Data Protection
- **Encrypted Storage**: API keys stored encrypted in database
- **Secure Transport**: WSS in production environments
- **Access Control**: User-based subscription isolation

### Input Validation
- **Parameter Validation**: Symbol, exchange, and mode validation
- **SQL Injection Prevention**: Parameterized queries
- **XSS Protection**: Output encoding for web interfaces

## Monitoring and Logging

### Service Layer Logging
```python
from utils.logging import get_logger

logger = get_logger(__name__)

# Connection events
logger.info(f"WebSocket connected for user {username}")
logger.error(f"Connection failed for user {username}: {error}")

# Subscription events  
logger.info(f"Subscribed to {len(symbols)} symbols for user {username}")
logger.warning(f"Subscription failed for {symbol}: {error}")

# Performance metrics
logger.info(f"Cache hit rate: {hit_rate:.2f}%")
```

### Metrics Collection
```python
# Performance metrics
{
    'connections': {
        'active': 45,
        'total': 1234,
        'failed': 12
    },
    'subscriptions': {
        'active': 890,
        'total': 5671,
        'errors': 23
    },
    'cache': {
        'hit_rate': 98.75,
        'total_requests': 12456,
        'memory_usage': '45MB'
    }
}
```

## Testing

### Unit Tests
```python
# tests/test_websocket_service.py
import pytest
from services.websocket_service import get_websocket_connection

def test_websocket_connection_success():
    success, client, error = get_websocket_connection('test_user')
    assert success == True
    assert client is not None
    assert error is None

def test_websocket_connection_no_api_key():
    success, client, error = get_websocket_connection('invalid_user')
    assert success == False
    assert client is None
    assert 'No API key found' in error
```

### Integration Tests
```python
# tests/test_websocket_integration.py
import asyncio
import websockets
import json

async def test_external_api_connection():
    """Test external SDK connection"""
    uri = "ws://localhost:8765"
    
    async with websockets.connect(uri) as websocket:
        # Authenticate
        await websocket.send(json.dumps({
            "action": "authenticate",
            "api_key": "test_api_key"
        }))
        
        # Receive auth response
        response = await websocket.recv()
        data = json.loads(response)
        
        assert data['status'] == 'success'
        assert data['type'] == 'auth'
```

## Migration Guide

### From Socket.IO to Direct WebSocket

#### Before (Socket.IO)
```python
from flask_socketio import emit

@socketio.on('subscribe')
def handle_subscribe(data):
    # Socket.IO event handling
    emit('subscription_success', {'status': 'subscribed'})
```

#### After (Service Layer)
```python
from services.websocket_service import subscribe_to_symbols

@websocket_bp.route('/api/websocket/subscribe', methods=['POST'])
def api_websocket_subscribe():
    data = request.get_json()
    success, result, status_code = subscribe_to_symbols(
        username, broker, symbols, mode
    )
    return jsonify(result), status_code
```

### Database Schema Updates
```sql
-- API keys table (existing)
CREATE TABLE api_keys (
    id INTEGER PRIMARY KEY,
    user_id STRING NOT NULL UNIQUE,
    api_key_hash TEXT NOT NULL,
    api_key_encrypted TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- No additional tables required for WebSocket service layer
```

## Best Practices

### Service Layer Development
1. **Consistent Return Types**: Always return (success, data, status_code) tuples
2. **Comprehensive Logging**: Log all connection and subscription events
3. **Error Handling**: Provide detailed error messages and codes
4. **Type Safety**: Use type hints for all function parameters and returns
5. **Resource Cleanup**: Ensure proper cleanup of connections and subscriptions

### External Integration
1. **API Key Security**: Never log or expose API keys in plain text
2. **Connection Management**: Implement proper reconnection logic
3. **Rate Limiting**: Respect server rate limits and implement backoff
4. **Error Recovery**: Handle network errors and service unavailability
5. **Documentation**: Provide clear integration examples and error codes

### Performance Optimization
1. **Connection Reuse**: Implement connection pooling for multiple requests
2. **Data Caching**: Cache frequently accessed market data
3. **Efficient Serialization**: Use binary protocols for high-frequency data
4. **Memory Management**: Monitor and limit memory usage
5. **Concurrent Access**: Design for high-concurrency environments

---

This service layer architecture provides a robust, scalable foundation for WebSocket-based real-time market data distribution while maintaining clean separation between external and internal access patterns.