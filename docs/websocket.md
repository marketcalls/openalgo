# OpenAlgo WebSocket Proxy Design

This document provides a high-level overview of the WebSocket proxy system for OpenAlgo. For detailed implementation code and examples, see:
- [websocket_auth_and_mapping.md](websocket_auth_and_mapping.md) - Authentication and symbol mapping implementation
- [websocket_implementation.md](websocket_implementation.md) - WebSocket adapter and proxy implementation
- [broker_factory.md](broker_factory.md) - Broker-agnostic factory design for supporting 20+ brokers
- [websocket_usage_example.md](websocket_usage_example.md) - Working example of subscribing to market data

## 1. System Overview

The OpenAlgo WebSocket Proxy is a scalable, broker-agnostic system that connects to various broker WebSocket APIs and provides a unified interface for clients to access real-time market data. Angel Broking is used as the pilot implementation, with the architecture designed to support 20+ brokers through a factory pattern. The system uses a publish-subscribe pattern with ZeroMQ as the message broker to efficiently distribute data to multiple consumers. The implementation is cross-platform compatible, with specific optimizations for Windows environments.

```
┌─────────────┐     ┌───────────────┐     ┌─────────────┐     ┌─────────────────┐
│ Broker DB   │ ──▶│ Auth Service  │────▶│ Client ID   │───▶│ API Key         │
│ (auth_db)   │     │ (get_tokens)  │     │ (user_id)   │     │ Validation      │
└─────────────┘     └───────────────┘     └─────────────┘     └─────────────────┘
       │                                                               │
       ▼                                                               ▼
┌─────────────┐     ┌───────────────┐     ┌─────────────┐     ┌─────────────────┐
│ Broker      │     │ Broker        │     │ ZeroMQ      │     │ Common          │
│ WebSocket   │◀───▶│ WebSocket     │───▶│ Pub/Sub     │────▶│ WebSocket      │
│ API         │     │ Adapter       │     │ Layer       │     │ Proxy           │
└─────────────┘     └───────────────┘     └─────────────┘     └─────────────────┘
                          ▲                                            │
                          │                                            ▼
                    ┌─────────────┐                           ┌─────────────────┐
                    │ Broker      │                           │ Client          │
                    │ Factory     │                           │ Applications    │
                    │             │                           │ (UI, Strategies)│
                    └─────────────┘                           └─────────────────┘
```

## 2. Key Components

### 2.1 Authentication Service

This component retrieves authentication tokens and client ID from the OpenAlgo database.

**Key Features:**
- Retrieves AUTH_TOKEN, FEED_TOKEN from auth_db.py
- Gets client ID (user_id) required for Angel WebSocket
- Validates API keys for client authentication
- Maintains connection between user accounts and broker sessions

### 2.2 Broker WebSocket Adapter

This component connects to a broker's WebSocket API using authentication tokens from the database. It's implemented as a base class with broker-specific adapters (currently Angel as the pilot implementation).

**Key Features:**
- Authenticates using broker-specific tokens (AUTH_TOKEN, FEED_TOKEN) and client ID
- Abstract interface that handles differences in message formats between brokers
- Implements robust reconnection with exponential backoff
- Manages subscriptions to all market data types (LTP, quote, depth)
- Factory pattern allows dynamic selection of the appropriate broker adapter

### 2.3 ZeroMQ Message Broker

Provides efficient message distribution between components using the publish-subscribe pattern.

**Key Features:**
- Topic-based filtering for efficient message routing
- High-throughput message passing
- Decouples producers from consumers
- Supports multiple subscribers for the same data

### 2.4 Common WebSocket Proxy

A unified WebSocket server that clients connect to for receiving market data.

**Key Features:**
- API key validation for secure connections
- Client subscription management
- Heartbeat mechanism for connection health monitoring
- Efficient message forwarding to interested clients
- Error handling and graceful degradation
- Cross-platform compatibility (Windows/Linux/Mac)
- Port availability checking and automatic port selection
- Resilient against crashes and unexpected shutdowns

## 3. Market Data Subscription Levels

The system supports the following subscription modes, with the BrokerCapabilityRegistry handling the differences in support across various brokers:

### 3.1 LTP Mode (Mode 1)
Basic last traded price updates with minimal data. Generally supported by all brokers.

### 3.2 Quote Mode (Mode 2)
Comprehensive quote information including LTP, volume, OHLC, etc. Supported by most brokers.

### 3.3 Market Depth Levels

#### 3.3.1 Depth (5 Level) - Mode 4
Standard market depth with 5 levels of buy/sell orders. Supported by all brokers.

#### 3.3.2 Depth (20 Level) - Mode 4 with extended parameter
Extended market depth with 20 levels. Support varies by broker and exchange:
- Angel: Supported on NSE & NFO exchanges
- Other brokers: Support determined via BrokerCapabilityRegistry

#### 3.3.3 Depth (30 Level) - Mode 4 with extended parameter
Full market depth with 30 levels. Limited broker support:
- Angel: Limited support on select exchanges (primarily NSE)
- Most other brokers: Not supported

#### 3.3.4 Depth (50 Level) - Mode 4 with extended parameter
Comprehensive market depth with 50 levels. Very limited broker support, primarily for institutional clients.

### 3.4 Broker Capability Registry

The system includes a capability registry that tracks which features and depth levels are supported by each broker and exchange combination. When a client requests a feature not supported by their broker, the system will:

1. Check if the requested feature is supported
2. If supported, process the request normally
3. If not supported but a fallback is available, use the fallback and notify the client
4. If no fallback is available, return an informative error message

## 4. Data Flow

### 4.1 Authentication Flow

1. Client connects to WebSocket Proxy with OpenAlgo API key
2. API key is validated against the database
3. System retrieves the user's active broker and associated tokens
4. Broker factory creates the appropriate adapter for the active broker
5. Broker WebSocket connection is established using broker-specific credentials

```
Client           WebSocket Proxy      Auth Service      Broker DB       Broker Factory
  │                    │                    │                │                 │
  │ connect(API_KEY)   │                    │                │                 │
  │───────────────────▶│                    │                │                 │
  │                    │ validate(API_KEY)  │                │                 │
  │                    │───────────────────▶│                │                 │
  │                    │                    │ get_tokens()   │                 │
  │                    │                    │───────────────▶│                 │
  │                    │                    │ tokens, user   │                 │
  │                    │                    │◀───────────────│                 │
  │                    │                    │                │                 │
  │                    │                    │ get_active_    │                 │
  │                    │                    │ broker(user)   │                 │
  │                    │                    │───────────────▶│                 │
  │                    │                    │ active_broker  │                 │
  │                    │                    │◀───────────────│                 │
  │                    │                    │                │                 │
  │                    │ create_adapter(broker_name)         │                 │
  │                    │────────────────────────────────────▶│                 │
  │                    │                    │                │ adapter         │
  │                    │◀───────────────────────────────────│                 │
  │  connection_ok     │                    │                │                 │
  │◀───────────────────│                    │                │                 │
  │                    │                    │                │                 │
```

### 4.2 Subscription Flow

1. Client sends subscription request with symbol, exchange, and mode
2. WebSocket Proxy maps symbol to broker-specific token using the mapping database
3. The appropriate broker adapter subscribes to the token via the broker's WebSocket API
4. Subscription confirmation is sent back to the client with capability support information

```
Client                WebSocket Proxy           Broker Adapter          Broker API
  │                        │                         │                      │
  │ subscribe(RELIANCE,    │                         │                      │
  │  NSE, MODE=4,          │                         │                      │
  │  DEPTH=20)             │                         │                      │
  │───────────────────────▶│                         │                      │
  │                        │ check_broker_capabilities(broker, exchange, depth)│
  │                        │────────────────────────▶│                      │
  │                        │ capabilities_response   │                      │
  │                        │◀────────────────────────│                      │
  │                        │                         │                      │
  │                        │ map_to_token(RELIANCE)  │                      │
  │                        │────────────────────────▶│                      │
  │                        │                         │ subscribe(token,     │
  │                        │                         │  mode=4, depth=20)   │
  │                        │                         │─────────────────────▶│
  │                        │                         │     success          │
  │                        │                         │◀─────────────────────│
  │  subscription_ok       │                         │                      │
  │  (with capability info)│                         │                      │
  │◀───────────────────────│                         │                      │
  │                        │                         │                      │
```

### 4.3 Market Data Flow

1. Broker API sends market data to the broker-specific WebSocket Adapter
2. Adapter normalizes data into a common format and publishes it to ZeroMQ
3. WebSocket Proxy subscribes to the ZeroMQ topics
4. Proxy forwards the data to interested clients

```
Broker API          Broker Adapter           ZeroMQ           WebSocket Proxy           Client
  │                     │                      │                   │                      │
  │  market_data        │                      │                   │                      │
  │────────────────────▶│                      │                   │                      │
  │                     │  normalize_data()    │                   │                      │
  │                     │  (broker-specific)   │                   │                      │
  │                     │                      │                   │                      │
  │                     │  publish(topic, data)│                   │                      │
  │                     │─────────────────────▶│                   │                      │
  │                     │                      │  subscribe(topic) │                      │
  │                     │                      │◀──────────────────│                      │
  │                     │                      │    data           │                      │
  │                     │                      │──────────────────▶│                      │
  │                     │                      │                   │   send(data)         │
  │                     │                      │                   │─────────────────────▶│
  │                     │                      │                   │                      │
```

## 5. Client Protocol

### 5.1 Connection & Authentication

```
ws://localhost:8765
```

Initial connection requires API key authentication:
```json
{
  "action": "authenticate", 
  "api_key": "YOUR_OPENALGO_API_KEY"
}
```

### 5.2 Subscription

Subscribe to different data modes:

```json
{
  "action": "subscribe",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "mode": 2  // 1=LTP, 2=QUOTE, 4=DEPTH
}
```

For depth subscriptions, you can specify the depth level:
```json
{
  "action": "subscribe",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "mode": 4,
  "depth_level": 20  // 5, 20, 30, or 50
}
```

The system will send appropriate error responses if the requested depth level is not supported by the broker:
```json
{
  "type": "error",
  "code": "UNSUPPORTED_DEPTH_LEVEL",
  "message": "Depth level 50 is not supported by broker Angel for exchange NSE",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "requested_mode": 4,
  "requested_depth": 50,
  "supported_depths": [5, 20]
}
```

### 5.3 Unsubscription

```json
{
  "action": "unsubscribe",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "mode": 2
}
```

## 6. Data Structure Formats

### 6.1 LTP Mode (Mode 1)

```json
{
  "type": "market_data",
  "mode": 1,
  "topic": "RELIANCE.NSE",
  "data": {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "ltp": 2500.50,
    "timestamp": "2025-04-16T10:30:45.123Z"
  }
}
```

### 6.2 Quote Mode (Mode 2)

```json
{
  "type": "market_data",
  "mode": 2,
  "topic": "RELIANCE.NSE",
  "data": {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "ltp": 2500.50,
    "change": 1.5,
    "change_percent": 0.06,
    "volume": 1000000,
    "open": 2490.00,
    "high": 2510.75,
    "low": 2485.25,
    "close": 2499.00,
    "last_trade_quantity": 10,
    "avg_trade_price": 2498.35,
    "timestamp": "2025-04-16T10:30:45.123Z"
  }
}
```

### 6.3 Depth Mode (Mode 4)

```json
{
  "type": "market_data",
  "mode": 4,
  "depth_level": 5,  // Can be 5, 20, 30, or 50
  "topic": "RELIANCE.NSE",
  "data": {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "ltp": 2500.50,
    "depth": {
      "buy": [
        {"price": 2500.25, "quantity": 100, "orders": 5},
        {"price": 2500.00, "quantity": 250, "orders": 12},
        {"price": 2499.75, "quantity": 300, "orders": 15},
        {"price": 2499.50, "quantity": 150, "orders": 8},
        {"price": 2499.25, "quantity": 200, "orders": 10}
        // Up to 50 levels depending on requested depth_level
      ],
      "sell": [
        {"price": 2500.75, "quantity": 150, "orders": 7},
        {"price": 2501.00, "quantity": 300, "orders": 15},
        {"price": 2501.25, "quantity": 200, "orders": 10},
        {"price": 2501.50, "quantity": 180, "orders": 8},
        {"price": 2501.75, "quantity": 120, "orders": 6}
        // Up to 50 levels depending on requested depth_level
      ]
    },
    "timestamp": "2025-04-16T10:30:45.123Z",
    "broker_supported": true  // Indicates if broker fully supports the requested depth level
  }
}
```

If a broker doesn't support the requested depth level but can provide a lower depth level, the system will return data with the available levels and indicate the limitation:

```json
{
  "type": "market_data",
  "mode": 4,
  "depth_level": 50,  // The requested depth level
  "actual_depth_level": 20,  // The actual depth level provided
  "topic": "RELIANCE.NSE",
  "data": {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "ltp": 2500.50,
    "depth": {
      "buy": [ /* 20 levels of data */ ],
      "sell": [ /* 20 levels of data */ ]
    },
    "timestamp": "2025-04-16T10:30:45.123Z",
    "broker_supported": false,  // Indicates broker limitation
    "broker_message": "Angel broker only supports up to 20 depth levels for NSE"
  }
}
```

## 7. Reliability Features

### 7.1 Heartbeat Mechanism

The system implements a bidirectional heartbeat mechanism:

1. **Angel to Adapter**: 
   - Angel's SmartWebSocketV2 sends regular heartbeats
   - Adapter monitors for missed heartbeats and reconnects if needed

2. **Proxy to Clients**:
   - WebSocket standard ping/pong mechanism (every 30 seconds)
   - Clients with 10-second timeout are considered disconnected

### 7.2 Reconnection Strategy

1. **Angel Adapter Reconnection**:
   - Exponential backoff with configurable parameters
   - Automatic resubscription to previous symbols
   - Connection state tracking to prevent duplicate connections

2. **Client Reconnection**:
   - Clients should implement reconnection logic
   - WebSocket proxy maintains subscription state for quick recovery

### 7.3 Angel Broker Implementation Notes

- **Price Format**: Angel broker sends prices in paise (1/100th of a rupee). The adapter automatically normalizes these values by dividing by 100 to get the actual price in rupees.
- **WebSocket Callback Compatibility**: The Angel adapter is designed to handle WebSocket callback parameters flexibly, ensuring compatibility with different versions of WebSocket libraries.

### 7.4 Error Handling

The WebSocket proxy system implements robust error handling at multiple levels:

1. **Connection Errors**:
   - Automatic recovery from network issues with exponential backoff
   - Notification to clients about connection status
   - Fallback mechanisms for temporary outages
   - Port conflict resolution and automatic port reassignment
   - Platform-specific handling for Windows and Unix-based systems

## 8. Implementation Plan

1. Set up project structure
2. Implement authentication service with API key validation
3. Create Angel WebSocket Adapter with client ID integration
4. Set up ZeroMQ pub/sub infrastructure
5. Create WebSocket proxy server with authentication
6. Implement symbol/token mapping
7. Add multi-level depth support (5/20/30)
8. Implement error handling and reconnection logic
9. Create client examples
10. Deploy and test in production environment

For detailed implementation code and examples, see:
- [websocket_auth_and_mapping.md](websocket_auth_and_mapping.md) - Authentication and symbol mapping implementation
- [websocket_implementation.md](websocket_implementation.md) - WebSocket adapter and proxy implementation
- [websocket_usage_example.md](websocket_usage_example.md) - Working example of subscribing to market data

## 9. Security Considerations

- **API Key Authentication**: All clients must provide a valid OpenAlgo API key
- **Authorization**: Role-based access control for different market data levels
- **Data Protection**: TLS encryption for all connections
- **Rate Limiting**: Prevention of excessive subscription requests
- **Session Management**: Proper session tracking and timeout handling

## 10. References

- [Angel WebSocket API Documentation](https://smartapi.angelbroking.com/docs/WebSocket2)
- [ZeroMQ Messaging Patterns](https://zguide.zeromq.org/docs/chapter2/)
- [WebSockets Protocol RFC6455](https://tools.ietf.org/html/rfc6455)
