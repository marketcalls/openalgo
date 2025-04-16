# OpenAlgo WebSocket Proxy Design

This document provides a high-level overview of the WebSocket proxy system for OpenAlgo. For detailed implementation code and examples, see [websocketprototype.md](websocketprototype.md).

## 1. System Overview

The OpenAlgo WebSocket Proxy is a scalable system that connects to broker WebSocket APIs (primarily Angel Broking) and provides a unified interface for clients to access real-time market data. The system uses a publish-subscribe pattern with ZeroMQ as the message broker to efficiently distribute data to multiple consumers.

```
┌─────────────┐     ┌───────────────┐     ┌─────────────┐     ┌─────────────────┐
│ Angel       │     │ Angel         │     │ ZeroMQ      │     │ Common          │n│ WebSocket   │────▶│ WebSocket     │────▶│ Pub/Sub     │────▶│ WebSocket      │
│ API         │     │ Adapter       │     │ Layer       │     │ Proxy          │
└─────────────┘     └───────────────┘     └─────────────┘     └─────────────────┘
                                                                      │
                                                                      ▼
                                                              ┌─────────────────┐
                                                              │ Client          │
                                                              │ Applications    │
                                                              │ (UI, Strategies)│
                                                              └─────────────────┘
```

## 2. Key Components

### 2.1 Angel WebSocket Adapter

This component connects to Angel's WebSocket API using authentication tokens from the OpenAlgo database.

**Key Features:**
- Authenticates using AUTH_TOKEN and FEED_TOKEN from the database
- Handles binary message parsing specific to Angel's format
- Implements robust reconnection with exponential backoff
- Manages subscriptions to different market data types (quotes, depth)

### 2.2 ZeroMQ Message Broker

Provides efficient message distribution between components using the publish-subscribe pattern.

**Key Features:**
- Topic-based filtering for efficient message routing
- High-throughput message passing
- Decouples producers from consumers
- Supports multiple subscribers for the same data

### 2.3 Common WebSocket Proxy

A unified WebSocket server that clients connect to for receiving market data.

**Key Features:**
- Client subscription management
- Heartbeat mechanism for connection health monitoring
- Efficient message forwarding to interested clients
- Error handling and graceful degradation

## 3. Data Flow

### 3.1 Subscription Flow

1. Client connects to WebSocket Proxy (`ws://localhost:8765`)
2. Client sends subscription request with symbol and exchange
3. WebSocket Proxy maps symbol to broker-specific token
4. Angel Adapter subscribes to the token via Angel WebSocket API
5. Subscription confirmation is sent back to the client

```
Client                WebSocket Proxy           Angel Adapter           Angel API
  │                        │                         │                      │
  │   subscribe(RELIANCE)  │                         │                      │
  │───────────────────────▶│                         │                      │
  │                        │   map_to_token(RELIANCE)│                      │
  │                        │────────────────────────▶│                      │
  │                        │                         │  subscribe(token)    │
  │                        │                         │─────────────────────▶│
  │                        │                         │     success          │
  │                        │                         │◀─────────────────────│
  │     subscription_ok    │                         │                      │
  │◀───────────────────────│                         │                      │
  │                        │                         │                      │
```

### 3.2 Market Data Flow

1. Angel API sends market data to Angel Adapter
2. Angel Adapter parses and normalizes the data
3. Data is published to ZeroMQ with appropriate topic
4. WebSocket Proxy receives data from ZeroMQ
5. WebSocket Proxy forwards data to subscribed clients

```
Angel API           Angel Adapter           ZeroMQ           WebSocket Proxy           Client
  │                     │                      │                   │                      │
  │  market_data        │                      │                   │                      │
  │────────────────────▶│                      │                   │                      │
  │                     │  publish(topic, data)│                   │                      │
  │                     │─────────────────────▶│                   │                      │
  │                     │                      │  data_for(topic)  │                      │
  │                     │                      │──────────────────▶│                      │
  │                     │                      │                   │  send_to_subscribers │
  │                     │                      │                   │─────────────────────▶│
  │                     │                      │                   │                      │
```

## 4. Client Protocol

### 4.1 Connection

```
ws://localhost:8765
```

### 4.2 Subscription

```json
{
  "action": "subscribe",
  "symbol": "RELIANCE",
  "exchange": "NSE"
}
```

### 4.3 Unsubscription

```json
{
  "action": "unsubscribe",
  "symbol": "RELIANCE",
  "exchange": "NSE"
}
```

### 4.4 Market Data Message

```json
{
  "type": "market_data",
  "topic": "RELIANCE.NSE",
  "data": {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "ltp": 2500.50,
    "change": 1.5,
    "volume": 1000000,
    "depth": {
      "buy": [
        {"price": 2500.25, "quantity": 100, "orders": 5},
        {"price": 2500.00, "quantity": 250, "orders": 12}
      ],
      "sell": [
        {"price": 2500.75, "quantity": 150, "orders": 7},
        {"price": 2501.00, "quantity": 300, "orders": 15}
      ]
    },
    "timestamp": "2025-04-16T10:30:45.123Z"
  }
}
```

## 5. Reliability Features

### 5.1 Heartbeat Mechanism

The system implements a bidirectional heartbeat mechanism:

1. **Angel to Adapter**: 
   - Angel's SmartWebSocketV2 sends regular heartbeats
   - Adapter monitors for missed heartbeats and reconnects if needed

2. **Proxy to Clients**:
   - WebSocket standard ping/pong mechanism (every 30 seconds)
   - Clients with 10-second timeout are considered disconnected

### 5.2 Reconnection Strategy

1. **Angel Adapter Reconnection**:
   - Exponential backoff with configurable parameters
   - Automatic resubscription to previous symbols
   - Connection state tracking to prevent duplicate connections

2. **Client Reconnection**:
   - Clients should implement reconnection logic
   - WebSocket proxy maintains subscription state for quick recovery

### 5.3 Error Handling

1. **Message Processing Errors**:
   - Graceful handling of malformed messages
   - Continued operation despite individual message failures
   - Comprehensive logging for troubleshooting

2. **Connection Errors**:
   - Automatic recovery from network issues
   - Notification to clients about connection status
   - Fallback mechanisms for temporary outages

## 6. Implementation Plan

1. Set up project structure
2. Implement Angel WebSocket Adapter
3. Set up ZeroMQ pub/sub infrastructure
4. Create WebSocket proxy server
5. Implement symbol/token mapping
6. Add error handling and reconnection logic
7. Set up logging and monitoring
8. Create client examples
9. Write tests
10. Deploy and test in production environment

For detailed implementation code and examples, see [websocketprototype.md](websocketprototype.md).

## 7. Deployment Considerations

- **Containerization**: Docker containers for each component
- **Scaling**: Horizontal scaling for WebSocket proxy
- **High Availability**: Multiple instances with load balancing
- **Monitoring**: Prometheus + Grafana dashboards

## 8. Security Considerations

- **Authentication**: JWT-based authentication for WebSocket clients
- **Authorization**: Role-based access control for market data
- **Data Protection**: TLS encryption for all connections
- **Rate Limiting**: Prevent abuse of the WebSocket API

## 9. References

- [Angel WebSocket API Documentation](https://smartapi.angelbroking.com/docs/WebSocket2)
- [ZeroMQ Messaging Patterns](https://zguide.zeromq.org/docs/chapter2/)
- [WebSockets Protocol RFC6455](https://tools.ietf.org/html/rfc6455)
