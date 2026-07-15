# Websockets

## OpenAlgo WebSocket Protocol Documentation

### Overview

The OpenAlgo WebSocket protocol allows clients to receive **real-time market data** using a standardized and broker-agnostic interface. It supports data streaming for **LTP (Last Traded Price)**, **Quotes (OHLC + Volume)**, and **Market Depth** (up to 50 levels depending on broker capability).

The protocol ensures efficient, scalable, and secure communication between client applications (such as trading bots, dashboards, or analytics tools) and the OpenAlgo platform. Authentication is handled using the OpenAlgo API key, and subscriptions are maintained per session.

### Version

* Protocol Version: 1.0
* Last Updated: May 28, 2025
* Platform: OpenAlgo Trading Framework

### WebSocket URL

```
ws://<host>:8765
```

Replace `<host>` with the IP/domain of your OpenAlgo instance. For local development setups, use thee hostname as`127.0.0.1`

```
ws://127.0.0.1:8765
```

In the production ubuntu server if your host is <https://yourdomain.com> then&#x20;

WebSocket url will be

```
wss://yourdomain.com/ws
```

In the production ubuntu server if your host is <https://sub.yourdomain.com> then&#x20;

WebSocket url will be

```
wss://sub.yourdomain.com/ws
```

### Authentication

All WebSocket sessions must begin with API key authentication:

```json
{
  "action": "authenticate", 
  "api_key": "YOUR_OPENALGO_API_KEY"
}
```

On success, the server confirms authentication. On failure, the connection is closed or an error message is returned.

### Data Modes

Clients can subscribe to different types of market data using the `mode` parameter. Each mode corresponds to a specific level of detail:

| Mode | Description    | Details                                    |
| ---- | -------------- | ------------------------------------------ |
| 1    | **LTP Mode**   | Last traded price and timestamp only       |
| 2    | **Quote Mode** | Includes OHLC, LTP, volume, change, etc.   |
| 3    | **Depth Mode** | Includes buy/sell order book (5–50 levels) |

> Note: Mode 3 supports optional parameter `depth_level` to define the number of depth levels requested (e.g., 5, 20, 30, 50). Actual support depends on the broker.

### Subscription Format

#### Basic Subscription

```json
{
  "action": "subscribe",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "mode": 1
}
```

#### Depth Subscription (with levels)

```json
{
  "action": "subscribe",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "mode": 3,
  "depth_level": 5
}
```

### Unsubscription

To unsubscribe from a stream:

```json
{
  "action": "unsubscribe",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "mode": 2
}
```

### Error Handling

If a client requests a depth level not supported by their broker:

```json
{
  "type": "error",
  "code": "UNSUPPORTED_DEPTH_LEVEL",
  "message": "Depth level 50 is not supported by broker Angel for exchange NSE",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "requested_mode": 3,
  "requested_depth": 50,
  "supported_depths": [5, 20]
}
```

### Market Data Format

#### LTP (Mode 1)

```json
{
  "type": "market_data",
  "mode": 1,
  "topic": "RELIANCE.NSE",
  "data": {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "ltp": 1424.0,
    "timestamp": "2025-05-28T10:30:45.123Z"
  }
}
```

#### Quote (Mode 2)

```json
{
  "type": "market_data",
  "mode": 2,
  "topic": "RELIANCE.NSE",
  "data": {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "ltp": 1424.0,
    "change": 6.0,
    "change_percent": 0.42,
    "volume": 100000,
    "open": 1415.0,
    "high": 1432.5,
    "low": 1408.0,
    "close": 1418.0,
    "last_trade_quantity": 50,
    "avg_trade_price": 1419.35,
    "timestamp": "2025-05-28T10:30:45.123Z"
  }
}
```

#### Depth (Mode 3 with depth\_level = 5)

```json
{
  "type": "market_data",
  "mode": 3,
  "depth_level": 5,
  "topic": "RELIANCE.NSE",
  "data": {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "ltp": 1424.0,
    "depth": {
      "buy": [
        {"price": 1423.9, "quantity": 50, "orders": 3},
        {"price": 1423.5, "quantity": 35, "orders": 2},
        {"price": 1423.0, "quantity": 42, "orders": 4},
        {"price": 1422.5, "quantity": 28, "orders": 1},
        {"price": 1422.0, "quantity": 33, "orders": 5}
      ],
      "sell": [
        {"price": 1424.1, "quantity": 47, "orders": 2},
        {"price": 1424.5, "quantity": 39, "orders": 3},
        {"price": 1425.0, "quantity": 41, "orders": 4},
        {"price": 1425.5, "quantity": 32, "orders": 2},
        {"price": 1426.0, "quantity": 30, "orders": 1}
      ]
    },
    "timestamp": "2025-05-28T10:30:45.123Z",
    "broker_supported": true
  }
}
```

### Order, Trade, and Position Channels

In addition to market data, the same WebSocket connection can stream **order lifecycle** updates so strategies don't have to poll `/api/v1/orderbook`, `/api/v1/tradebook`, or `/api/v1/positionbook`. Three channels are available: `order_update`, `trade_update`, and `position_update`.

Unlike market-data subscriptions, these channels take no `symbol`/`exchange`/`mode` — OpenAlgo is single-user/single-broker per deployment, so there is exactly one account's stream to subscribe to.

#### Subscribing

```json
{
  "action": "subscribe",
  "channel": "order_update"
}
```

Send one `subscribe` request per channel (`order_update`, `trade_update`, `position_update`) for the events you want. The server acknowledges:

```json
{
  "type": "subscribe",
  "channel": "order_update",
  "status": "success"
}
```

Immediately after a successful subscribe, if a snapshot is available, the server sends the current state of all open orders/trades/positions so the client isn't left waiting for the next change:

```json
{
  "type": "order_update",
  "snapshot": true,
  "generation": 42,
  "data": {
    "generation": 42,
    "orders": [ /* ... */ ],
    "trades": [ /* ... */ ],
    "positions": [ /* ... */ ]
  }
}
```

No snapshot is sent if analyzer/sandbox mode is active (fills are pushed in real time as they happen, so there's nothing to snapshot yet) or if the poller hasn't completed its first cycle — this is expected, not an error.

#### Unsubscribing

```json
{
  "action": "unsubscribe",
  "channel": "order_update"
}
```

#### Event Payloads

Every event carries `event_type`, `generation`, and `sequence`. Within one poll cycle, events are always delivered in canonical order — `order_update` before `trade_update` before `position_update` for the same execution — so a client never observes a fill before the order status change that produced it.

**`order_update`**

```json
{
  "type": "order_update",
  "data": {
    "event_type": "order_update",
    "generation": 43,
    "sequence": 0,
    "orderid": "250714000012345",
    "symbol": "SBIN",
    "exchange": "NSE",
    "action": "BUY",
    "product": "MIS",
    "pricetype": "LIMIT",
    "quantity": 10,
    "price": 825.5,
    "trigger_price": 0.0,
    "status": "complete",
    "rejection_reason": "",
    "timestamp": "2026-07-15 09:16:23"
  }
}
```

`status` follows the standard OpenAlgo order-status values: `open`, `trigger pending`, `complete`, `rejected`, `cancelled`.

**`trade_update`**

```json
{
  "type": "trade_update",
  "data": {
    "event_type": "trade_update",
    "generation": 43,
    "sequence": 1,
    "orderid": "250714000012345",
    "tradeid": "250714000012345:10:825.5:2026-07-15 09:16:23",
    "symbol": "SBIN",
    "exchange": "NSE",
    "product": "MIS",
    "action": "BUY",
    "fill_quantity": 10,
    "fill_price": 825.5,
    "trade_value": 8255.0,
    "timestamp": "2026-07-15 09:16:23"
  }
}
```

**`position_update`**

```json
{
  "type": "position_update",
  "data": {
    "event_type": "position_update",
    "generation": 43,
    "sequence": 2,
    "symbol": "SBIN",
    "exchange": "NSE",
    "product": "MIS",
    "net_quantity": 10,
    "average_price": 825.5,
    "ltp": 826.0,
    "pnl": 5.0,
    "timestamp": ""
  }
}
```

#### How This Works

A background poller (one per broker session, shared across every browser tab/device the user has open) polls the broker's orderbook/tradebook/positions and diffs against the last snapshot — most brokers don't offer a push feed for order status, so this keeps behavior broker-agnostic across all 30+ integrations without any broker-specific code. Polling is adaptive: it runs at a conservative baseline and briefly speeds up right after OpenAlgo places, modifies, or cancels an order (or while an order remains non-terminal), then settles back down — never a standing aggressive interval, since the poll budget is shared with real trading calls on the same broker session. Analyzer/sandbox mode bypasses polling entirely and pushes fills the instant they happen. Poll intervals are configurable via `.env` (`ORDER_POLL_NORMAL_MS`, `ORDER_POLL_FAST_MS`, `TRADE_POLL_NORMAL_MS`, `TRADE_POLL_FAST_MS`, `POSITION_POLL_MS`, `FAST_MODE_TIMEOUT_SEC`).

### Heartbeat and Reconnection

* Server sends `ping` messages every 30 seconds.
* Clients must respond with `pong` or will be disconnected.
* Upon reconnection, clients must re-authenticate and re-subscribe to streams.
* Proxy may automatically restore prior subscriptions if supported by broker.

### Security & Compliance

* All clients must authenticate with an API key.
* Unauthorized or malformed requests are rejected.
* Rate limits may apply to prevent abuse.
* TLS encryption recommended for production deployments.

The OpenAlgo WebSocket feed provides a reliable and structured method for receiving real-time trading data. Proper mode selection and parsing allow efficient integration into trading algorithms and monitoring systems.


---

# Agent Instructions: Querying This Documentation

If you need additional information that is not directly available in this page, you can query the documentation dynamically by asking a question.

Perform an HTTP GET request on the current page URL with the `ask` query parameter:

```
GET https://docs.openalgo.in/api-documentation/v1/websockets.md?ask=<question>
```

The question should be specific, self-contained, and written in natural language.
The response will contain a direct answer to the question and relevant excerpts and sources from the documentation.

Use this mechanism when the answer is not explicitly present in the current page, you need clarification or additional context, or you want to retrieve related documentation sections.
