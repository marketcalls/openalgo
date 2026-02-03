# PRD: WebSocket Proxy - Real-Time Market Data

> **Status:** ✅ Stable - Fully implemented with connection pooling

## Overview

The WebSocket Proxy is a unified real-time market data streaming system that normalizes data from 24+ broker WebSocket APIs into a single interface.

## Problem Statement

Each broker has:
- Different WebSocket protocols and formats
- Different symbol formats and token systems
- Different subscription limits (500-3000 symbols)
- Connection management complexity

Clients need:
- Single WebSocket connection for all data
- Consistent data format regardless of broker
- High-performance streaming for 1000s of symbols

## Solution

A proxy server that:
- Connects to broker-specific WebSocket APIs
- Normalizes data to OpenAlgo format
- Uses ZeroMQ for high-performance internal messaging
- Supports connection pooling for scale

## Target Users

| User | Use Case |
|------|----------|
| React Frontend | Display live prices |
| Python Scripts | Algo trading signals |
| External Apps | Custom dashboards |

## Functional Requirements

### FR1: Client Management
| ID | Requirement | Priority |
|----|-------------|----------|
| FR1.1 | Accept WebSocket connections on port 8765 | P0 |
| FR1.2 | API key authentication | P0 |
| FR1.3 | Track client subscriptions | P0 |
| FR1.4 | Handle client disconnect gracefully | P0 |

### FR2: Subscription Management
| ID | Requirement | Priority |
|----|-------------|----------|
| FR2.1 | Subscribe to symbols (LTP mode) | P0 |
| FR2.2 | Subscribe to symbols (Quote mode) | P0 |
| FR2.3 | Subscribe to symbols (Depth mode) | P1 |
| FR2.4 | Unsubscribe from symbols | P0 |
| FR2.5 | Subscription index for O(1) lookup | P0 |

### FR3: Broker Adapters
| ID | Requirement | Priority |
|----|-------------|----------|
| FR3.1 | Abstract base adapter class | P0 |
| FR3.2 | Zerodha (Kite) adapter | P0 |
| FR3.3 | Angel One adapter | P0 |
| FR3.4 | Dhan adapter | P0 |
| FR3.5 | Other broker adapters (20+) | P1 |
| FR3.6 | Symbol mapping per broker | P0 |

### FR4: Connection Pooling
| ID | Requirement | Priority |
|----|-------------|----------|
| FR4.1 | Multiple connections per broker | P1 |
| FR4.2 | Configurable symbols per connection | P0 |
| FR4.3 | Auto-distribute subscriptions | P1 |
| FR4.4 | Handle connection failures | P0 |

### FR5: Data Normalization
| ID | Requirement | Priority |
|----|-------------|----------|
| FR5.1 | Normalize LTP data | P0 |
| FR5.2 | Normalize OHLC quote data | P0 |
| FR5.3 | Normalize market depth (5 levels) | P1 |
| FR5.4 | Add timestamp if missing | P0 |

### FR6: Performance
| ID | Requirement | Priority |
|----|-------------|----------|
| FR6.1 | Message throttling (50ms minimum) | P0 |
| FR6.2 | Batch message sending | P1 |
| FR6.3 | ZeroMQ pub/sub for internal routing | P0 |

## Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Latency (broker → client) | < 50ms |
| Concurrent clients | 100+ |
| Symbols per user | 3000 |
| Message throughput | 10,000/sec |
| Uptime | 99.9% during market hours |

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Clients                                      │
│  React App │ Python SDK │ External Apps                             │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ WebSocket (ws://localhost:8765)
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    WebSocket Proxy Server                            │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                   Connection Manager                            │ │
│  │  clients: Dict[client_id, websocket]                           │ │
│  │  subscriptions: Dict[client_id, Set[symbols]]                  │ │
│  │  subscription_index: Dict[(sym,exch,mode), Set[client_ids]]    │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                               │                                      │
│                               │ ZeroMQ (tcp://127.0.0.1:5555)       │
│                               ▼                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                    Broker Adapters                              │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │ │
│  │  │ Zerodha  │ │  Angel   │ │   Dhan   │ │  Fyers   │  ...     │ │
│  │  │ 3000 sym │ │ 1000 sym │ │ 1000 sym │ │ 2000 sym │          │ │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘          │ │
│  │       │            │            │            │                  │ │
│  │       └────────────┴────────────┴────────────┘                  │ │
│  │                         │                                       │ │
│  │                         ▼ Broker WebSocket APIs                 │ │
│  └────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

## Message Protocol

### Authentication
```json
→ {"action": "authenticate", "api_key": "your_api_key"}
← {"status": "authenticated", "message": "Connected"}
```

### Subscribe
```json
→ {
    "action": "subscribe",
    "symbols": [
      {"symbol": "SBIN", "exchange": "NSE"},
      {"symbol": "RELIANCE", "exchange": "NSE"}
    ],
    "mode": "LTP"
  }
← {"status": "subscribed", "count": 2}
```

### Market Data (LTP)
```json
← {
    "symbol": "SBIN",
    "exchange": "NSE",
    "ltp": 625.50,
    "timestamp": "2024-01-15T10:30:00+05:30"
  }
```

### Market Data (Quote)
```json
← {
    "symbol": "SBIN",
    "exchange": "NSE",
    "ltp": 625.50,
    "open": 620.00,
    "high": 628.00,
    "low": 618.50,
    "close": 622.00,
    "volume": 1500000,
    "timestamp": "2024-01-15T10:30:00+05:30"
  }
```

### Market Data (Depth)
```json
← {
    "symbol": "SBIN",
    "exchange": "NSE",
    "ltp": 625.50,
    "depth": {
      "buy": [
        {"price": 625.45, "quantity": 1000, "orders": 5},
        {"price": 625.40, "quantity": 2500, "orders": 8}
      ],
      "sell": [
        {"price": 625.50, "quantity": 800, "orders": 3},
        {"price": 625.55, "quantity": 1200, "orders": 4}
      ]
    }
  }
```

## ZeroMQ Integration

```
┌─────────────────┐         ┌─────────────────┐
│ Broker Adapter  │         │ Broker Adapter  │
│   (Publisher)   │         │   (Publisher)   │
└────────┬────────┘         └────────┬────────┘
         │                           │
         │    ZeroMQ PUB/SUB         │
         │    tcp://127.0.0.1:5555   │
         └───────────┬───────────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │    WebSocket Proxy    │
         │     (Subscriber)      │
         │                       │
         │  Receives all ticks   │
         │  Routes to clients    │
         └───────────────────────┘
```

## Configuration

```bash
# Environment Variables
WEBSOCKET_HOST=127.0.0.1
WEBSOCKET_PORT=8765
ZMQ_HOST=127.0.0.1
ZMQ_PORT=5555
MAX_SYMBOLS_PER_WEBSOCKET=1000
MAX_WEBSOCKET_CONNECTIONS=3
```

## Broker Symbol Limits

| Broker | Max Symbols/Connection | Pool Size | Total |
|--------|------------------------|-----------|-------|
| Zerodha | 3000 | 1 | 3000 |
| Angel | 1000 | 3 | 3000 |
| Dhan | 1000 | 3 | 3000 |
| Fyers | 2000 | 2 | 4000 |
| Others | 1000 | 3 | 3000 |

## App Integration

The WebSocket server runs as a daemon thread inside the main Flask app:

```python
# app.py
from websocket_proxy.app_integration import start_websocket_proxy
start_websocket_proxy(app)

# Lifecycle:
# 1. Flask starts
# 2. WebSocket thread spawns (port 8765)
# 3. Both run in same process
# 4. Cleanup on shutdown
```

**Important:** Single Gunicorn worker (`-w 1`) required.

## Key Files

| File | Purpose |
|------|---------|
| `websocket_proxy/server.py` | Main WebSocketProxy class with ZMQ subscription |
| `websocket_proxy/connection_manager.py` | ConnectionPool and SharedZmqPublisher for pooling |
| `websocket_proxy/base_adapter.py` | Abstract broker adapter base class |
| `websocket_proxy/broker_factory.py` | Adapter factory for broker discovery |
| `websocket_proxy/app_integration.py` | Flask startup/shutdown integration |
| `broker/*/streaming/*_adapter.py` | Broker-specific adapter implementations |

## Success Metrics

| Metric | Target |
|--------|--------|
| Message latency | < 50ms |
| Connection stability | 99.9% uptime |
| Symbols supported | 3000 per user |
| Concurrent users | 100+ |
