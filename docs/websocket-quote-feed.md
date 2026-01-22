# WebSocket Quote Feed - Integration Guide

This guide demonstrates how to integrate with OpenAlgo's WebSocket quote feed for real-time market data streaming.

## Overview

OpenAlgo provides a unified WebSocket server (port 8765) that streams market data from 24+ brokers in a normalized format. Clients can subscribe to LTP, Quote, or Depth modes.

## Connection Details

| Parameter | Value |
|-----------|-------|
| Host | `127.0.0.1` or your server IP |
| Port | `8765` |
| Protocol | `ws://` or `wss://` (with SSL) |
| Authentication | API key required |

## Message Protocol

### 1. Authentication

```json
// Request
{
    "action": "authenticate",
    "api_key": "your_64_char_api_key"
}

// Response
{
    "status": "authenticated",
    "message": "Connected to OpenAlgo WebSocket"
}
```

### 2. Subscribe (LTP Mode)

```json
// Request
{
    "action": "subscribe",
    "symbols": [
        {"symbol": "SBIN", "exchange": "NSE"},
        {"symbol": "RELIANCE", "exchange": "NSE"}
    ],
    "mode": "LTP"
}

// Response
{
    "status": "subscribed",
    "count": 2,
    "symbols": ["SBIN.NSE", "RELIANCE.NSE"]
}
```

### 3. Subscribe (Quote Mode)

```json
// Request
{
    "action": "subscribe",
    "symbols": [
        {"symbol": "SBIN", "exchange": "NSE"}
    ],
    "mode": "QUOTE"
}
```

### 4. Subscribe (Depth Mode)

```json
// Request
{
    "action": "subscribe",
    "symbols": [
        {"symbol": "NIFTY24JAN24000CE", "exchange": "NFO"}
    ],
    "mode": "DEPTH"
}
```

### 5. Unsubscribe

```json
// Request
{
    "action": "unsubscribe",
    "symbols": [
        {"symbol": "SBIN", "exchange": "NSE"}
    ]
}

// Response
{
    "status": "unsubscribed",
    "count": 1
}
```

## Data Formats

### LTP Data

```json
{
    "type": "market_data",
    "mode": "LTP",
    "symbol": "SBIN",
    "exchange": "NSE",
    "ltp": 625.50,
    "timestamp": "2024-01-15T10:30:00+05:30"
}
```

### Quote Data

```json
{
    "type": "market_data",
    "mode": "QUOTE",
    "symbol": "SBIN",
    "exchange": "NSE",
    "ltp": 625.50,
    "open": 620.00,
    "high": 628.00,
    "low": 618.50,
    "close": 622.00,
    "volume": 1500000,
    "change": 3.50,
    "change_percent": 0.56,
    "timestamp": "2024-01-15T10:30:00+05:30"
}
```

### Depth Data

```json
{
    "type": "market_data",
    "mode": "DEPTH",
    "symbol": "SBIN",
    "exchange": "NSE",
    "ltp": 625.50,
    "depth": {
        "buy": [
            {"price": 625.45, "quantity": 1000, "orders": 5},
            {"price": 625.40, "quantity": 2500, "orders": 8},
            {"price": 625.35, "quantity": 1800, "orders": 6},
            {"price": 625.30, "quantity": 3200, "orders": 12},
            {"price": 625.25, "quantity": 2100, "orders": 7}
        ],
        "sell": [
            {"price": 625.50, "quantity": 800, "orders": 3},
            {"price": 625.55, "quantity": 1200, "orders": 4},
            {"price": 625.60, "quantity": 1500, "orders": 5},
            {"price": 625.65, "quantity": 2000, "orders": 6},
            {"price": 625.70, "quantity": 1700, "orders": 5}
        ]
    },
    "timestamp": "2024-01-15T10:30:00+05:30"
}
```

## Python Client Example

### Basic Connection

```python
import asyncio
import websockets
import json

async def connect_quote_feed():
    uri = "ws://127.0.0.1:8765"
    api_key = "your_64_char_api_key"

    async with websockets.connect(uri) as ws:
        # Authenticate
        await ws.send(json.dumps({
            "action": "authenticate",
            "api_key": api_key
        }))
        response = await ws.recv()
        print(f"Auth: {response}")

        # Subscribe to symbols
        await ws.send(json.dumps({
            "action": "subscribe",
            "symbols": [
                {"symbol": "SBIN", "exchange": "NSE"},
                {"symbol": "RELIANCE", "exchange": "NSE"}
            ],
            "mode": "QUOTE"
        }))
        response = await ws.recv()
        print(f"Subscribe: {response}")

        # Receive market data
        while True:
            data = await ws.recv()
            tick = json.loads(data)
            print(f"{tick['symbol']}: {tick['ltp']}")

asyncio.run(connect_quote_feed())
```

### With Reconnection

```python
import asyncio
import websockets
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class QuoteFeedClient:
    def __init__(self, host="127.0.0.1", port=8765, api_key=None):
        self.uri = f"ws://{host}:{port}"
        self.api_key = api_key
        self.ws = None
        self.subscriptions = []
        self.reconnect_delay = 5

    async def connect(self):
        while True:
            try:
                self.ws = await websockets.connect(self.uri)
                logger.info("Connected to WebSocket")

                # Authenticate
                await self._authenticate()

                # Resubscribe if reconnecting
                if self.subscriptions:
                    await self._resubscribe()

                # Start receiving
                await self._receive_loop()

            except websockets.ConnectionClosed:
                logger.warning("Connection closed, reconnecting...")
                await asyncio.sleep(self.reconnect_delay)
            except Exception as e:
                logger.error(f"Error: {e}")
                await asyncio.sleep(self.reconnect_delay)

    async def _authenticate(self):
        await self.ws.send(json.dumps({
            "action": "authenticate",
            "api_key": self.api_key
        }))
        response = await self.ws.recv()
        data = json.loads(response)
        if data.get("status") != "authenticated":
            raise Exception("Authentication failed")
        logger.info("Authenticated")

    async def subscribe(self, symbols, mode="QUOTE"):
        self.subscriptions = symbols
        await self.ws.send(json.dumps({
            "action": "subscribe",
            "symbols": symbols,
            "mode": mode
        }))
        response = await self.ws.recv()
        logger.info(f"Subscribed: {response}")

    async def _resubscribe(self):
        await self.ws.send(json.dumps({
            "action": "subscribe",
            "symbols": self.subscriptions,
            "mode": "QUOTE"
        }))
        response = await self.ws.recv()
        logger.info(f"Resubscribed: {response}")

    async def _receive_loop(self):
        async for message in self.ws:
            data = json.loads(message)
            await self.on_tick(data)

    async def on_tick(self, tick):
        """Override this method to handle ticks"""
        print(f"{tick.get('symbol')}: {tick.get('ltp')}")

# Usage
async def main():
    client = QuoteFeedClient(api_key="your_api_key")

    # Start connection in background
    connect_task = asyncio.create_task(client.connect())

    # Wait for connection
    await asyncio.sleep(2)

    # Subscribe to symbols
    await client.subscribe([
        {"symbol": "SBIN", "exchange": "NSE"},
        {"symbol": "RELIANCE", "exchange": "NSE"},
        {"symbol": "INFY", "exchange": "NSE"}
    ])

    # Keep running
    await connect_task

asyncio.run(main())
```

## JavaScript/Browser Example

```javascript
class QuoteFeedClient {
    constructor(host = '127.0.0.1', port = 8765, apiKey) {
        this.url = `ws://${host}:${port}`;
        this.apiKey = apiKey;
        this.ws = null;
        this.onTick = () => {};
    }

    connect() {
        this.ws = new WebSocket(this.url);

        this.ws.onopen = () => {
            console.log('Connected');
            this.authenticate();
        };

        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);

            if (data.status === 'authenticated') {
                console.log('Authenticated');
            } else if (data.type === 'market_data') {
                this.onTick(data);
            }
        };

        this.ws.onclose = () => {
            console.log('Disconnected, reconnecting...');
            setTimeout(() => this.connect(), 5000);
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    }

    authenticate() {
        this.ws.send(JSON.stringify({
            action: 'authenticate',
            api_key: this.apiKey
        }));
    }

    subscribe(symbols, mode = 'QUOTE') {
        this.ws.send(JSON.stringify({
            action: 'subscribe',
            symbols: symbols,
            mode: mode
        }));
    }

    unsubscribe(symbols) {
        this.ws.send(JSON.stringify({
            action: 'unsubscribe',
            symbols: symbols
        }));
    }
}

// Usage
const client = new QuoteFeedClient('127.0.0.1', 8765, 'your_api_key');

client.onTick = (tick) => {
    console.log(`${tick.symbol}: ${tick.ltp}`);
    // Update UI
    document.getElementById(`price-${tick.symbol}`).textContent = tick.ltp;
};

client.connect();

// Subscribe after connection
setTimeout(() => {
    client.subscribe([
        { symbol: 'SBIN', exchange: 'NSE' },
        { symbol: 'RELIANCE', exchange: 'NSE' }
    ]);
}, 2000);
```

## React Hook Example

```typescript
import { useEffect, useRef, useState, useCallback } from 'react';

interface Tick {
    symbol: string;
    exchange: string;
    ltp: number;
    open?: number;
    high?: number;
    low?: number;
    close?: number;
    volume?: number;
    timestamp: string;
}

interface UseQuoteFeedOptions {
    host?: string;
    port?: number;
    apiKey: string;
    symbols: Array<{ symbol: string; exchange: string }>;
    mode?: 'LTP' | 'QUOTE' | 'DEPTH';
}

export function useQuoteFeed(options: UseQuoteFeedOptions) {
    const {
        host = '127.0.0.1',
        port = 8765,
        apiKey,
        symbols,
        mode = 'QUOTE'
    } = options;

    const ws = useRef<WebSocket | null>(null);
    const [ticks, setTicks] = useState<Map<string, Tick>>(new Map());
    const [isConnected, setIsConnected] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const connect = useCallback(() => {
        ws.current = new WebSocket(`ws://${host}:${port}`);

        ws.current.onopen = () => {
            setIsConnected(true);
            setError(null);

            // Authenticate
            ws.current?.send(JSON.stringify({
                action: 'authenticate',
                api_key: apiKey
            }));
        };

        ws.current.onmessage = (event) => {
            const data = JSON.parse(event.data);

            if (data.status === 'authenticated') {
                // Subscribe to symbols
                ws.current?.send(JSON.stringify({
                    action: 'subscribe',
                    symbols,
                    mode
                }));
            } else if (data.type === 'market_data') {
                setTicks(prev => {
                    const next = new Map(prev);
                    next.set(`${data.symbol}.${data.exchange}`, data);
                    return next;
                });
            }
        };

        ws.current.onclose = () => {
            setIsConnected(false);
            // Reconnect after 5 seconds
            setTimeout(connect, 5000);
        };

        ws.current.onerror = () => {
            setError('WebSocket connection error');
        };
    }, [host, port, apiKey, symbols, mode]);

    useEffect(() => {
        connect();
        return () => {
            ws.current?.close();
        };
    }, [connect]);

    return { ticks, isConnected, error };
}

// Usage in component
function StockPrices() {
    const { ticks, isConnected } = useQuoteFeed({
        apiKey: 'your_api_key',
        symbols: [
            { symbol: 'SBIN', exchange: 'NSE' },
            { symbol: 'RELIANCE', exchange: 'NSE' }
        ],
        mode: 'QUOTE'
    });

    return (
        <div>
            <div>Status: {isConnected ? 'Connected' : 'Disconnected'}</div>
            {Array.from(ticks.values()).map(tick => (
                <div key={`${tick.symbol}.${tick.exchange}`}>
                    {tick.symbol}: {tick.ltp} ({tick.change_percent}%)
                </div>
            ))}
        </div>
    );
}
```

## Error Handling

### Common Error Responses

```json
// Invalid API key
{
    "status": "error",
    "code": "INVALID_API_KEY",
    "message": "API key authentication failed"
}

// Symbol not found
{
    "status": "error",
    "code": "SYMBOL_NOT_FOUND",
    "message": "Symbol INVALID not found for exchange NSE"
}

// Not authenticated
{
    "status": "error",
    "code": "NOT_AUTHENTICATED",
    "message": "Please authenticate first"
}

// Subscription limit exceeded
{
    "status": "error",
    "code": "LIMIT_EXCEEDED",
    "message": "Maximum subscription limit of 3000 symbols reached"
}
```

## Best Practices

1. **Authenticate first**: Always authenticate before subscribing
2. **Handle reconnection**: Implement automatic reconnection logic
3. **Resubscribe on reconnect**: Maintain subscription list and resubscribe after reconnection
4. **Use appropriate mode**: Use LTP for price-only, QUOTE for OHLCV, DEPTH for order book
5. **Limit subscriptions**: Stay within the 3000 symbol limit
6. **Process asynchronously**: Don't block on tick processing

## Symbol Limits

| Broker | Per Connection | Pool Size | Total |
|--------|----------------|-----------|-------|
| Zerodha | 3000 | 1 | 3000 |
| Angel | 1000 | 3 | 3000 |
| Dhan | 1000 | 3 | 3000 |
| Others | 1000 | 3 | 3000 |

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Connection refused | Check WebSocket server is running |
| Authentication failed | Verify API key is correct |
| No data received | Confirm subscription was successful |
| Disconnections | Implement reconnection with exponential backoff |
