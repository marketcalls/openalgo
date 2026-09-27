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

> Note: Mode 3 supports optional request field `depth` to define the number of
> depth levels requested (for example 5, 20, 30 or 50). Actual support depends
> on the broker. Modes may be sent as `1`/`2`/`3` or the case-insensitive labels
> `LTP`/`Quote`/`Depth`.

### Subscription Format

#### Basic Subscription

```json
{
  "action": "subscribe",
  "symbols": [
    {"symbol": "RELIANCE", "exchange": "NSE"}
  ],
  "mode": "LTP"
}
```

#### Depth Subscription (with levels)

```json
{
  "action": "subscribe",
  "symbols": [
    {"symbol": "RELIANCE", "exchange": "NSE"}
  ],
  "mode": "Depth",
  "depth": 5
}
```

### Unsubscription

To unsubscribe from a stream:

```json
{
  "action": "unsubscribe",
  "symbols": [
    {"symbol": "RELIANCE", "exchange": "NSE"}
  ],
  "mode": "Quote",
  "request_id": "req-7"
}
```

For an array request, a `mode` on an individual symbol wins; otherwise the
top-level `mode` applies, and only a request with neither defaults to `Quote`.
For mode-valid requests, the acknowledgement identifies the exact canonical
mode on each successful or failed item. When mode validation itself fails, the
failed item cannot have a canonical label, so its `mode` is `null`:

```json
{
  "type": "unsubscribe",
  "status": "success",
  "message": "Unsubscription processing complete",
  "successful": [
    {
      "symbol": "RELIANCE",
      "exchange": "NSE",
      "mode": "Quote",
      "status": "success",
      "broker": "zerodha"
    }
  ],
  "failed": [],
  "broker": "zerodha",
  "request_id": "req-7"
}
```

For the final client that owns a broker subscription, local ownership is
removed only after the adapter returns success. A failed or malformed broker
response leaves the subscription registered so the caller can retry. When
another client still owns the exact symbol, exchange and mode, only the
requesting client's local owner is removed and the broker stream stays active.
A socket disconnect is terminal for that client session, so its registry owner
is removed after the server's cleanup attempt. A release that still fails is
reclaimed by last-client adapter teardown; the persistent Flattrade or Shoonya
adapter is retained only after `unsubscribe_all` acknowledges success.

### Error Handling

Subscription failures are reported on the subscribe acknowledgement, one
result per symbol. If a broker refuses the requested depth, the wire shape is:

```json
{
  "type": "subscribe",
  "status": "partial",
  "subscriptions": [
    {
      "symbol": "RELIANCE",
      "exchange": "NSE",
      "status": "error",
      "message": "Depth level 50 is not supported by this broker",
      "broker": "angel"
    }
  ],
  "message": "Subscription processing complete",
  "broker": "angel"
}
```

`status` is `partial` when at least one symbol failed and `success` only when
every requested symbol succeeded. Adapter messages are broker-specific; there
is no standardized top-level error code for this case.

### Market Data Format

#### LTP (Mode 1)

```json
{
  "type": "market_data",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "mode": 1,
  "broker": "zerodha",
  "data": {
    "ltp": 1424.0,
    "timestamp": 1756376445123
  }
}
```

#### Quote (Mode 2)

```json
{
  "type": "market_data",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "mode": 2,
  "broker": "zerodha",
  "data": {
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
    "timestamp": 1756376445123
  }
}
```

#### Depth (Mode 3 with `depth` = 5)

```json
{
  "type": "market_data",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "mode": 3,
  "broker": "zerodha",
  "data": {
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
    "timestamp": 1756376445123
  }
}
```

### Order Updates (Account-Level Stream)

Real-time order status changes (fills, partial fills, rejections,
cancellations) pushed by the broker — or by the sandbox engine in analyze
mode. No symbols or modes; one subscription covers the whole account.

Subscribe (after authentication):

```json
{
  "action": "subscribe_orders"
}
```

Unsubscribe with `{"action": "unsubscribe_orders"}`. Each event arrives as:

```json
{
  "type": "order_update",
  "user_id": "openalgo-user",
  "mode": "live",
  "broker": "upstox",
  "orderid": "240221025997024",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "action": "BUY",
  "quantity": 10,
  "price": 1424.0,
  "trigger_price": 0,
  "pricetype": "LIMIT",
  "product": "MIS",
  "order_status": "complete",
  "filled_quantity": 10,
  "pending_quantity": 0,
  "average_price": 1423.85,
  "rejection_reason": ""
}
```

Fields use OpenAlgo's common order constants: `symbol` is in OpenAlgo symbol
format (mapped from the broker's own symbology, e.g. `NHPC-EQ` → `NHPC`,
`NIFTY28JUL26FUT` for NFO futures), `action` BUY/SELL, `pricetype`
MARKET/LIMIT/SL/SL-M, `product` CNC/NRML/MIS; `order_status` is lowercase
`open` / `trigger pending` / `complete` / `rejected` / `cancelled` (plus broker extras such as
`expired`); `rejection_reason` carries the broker's full RMS/OMS text when
rejected; `mode` is `live` (broker) or `analyze` (sandbox).

Sources: dedicated broker order feeds (Zerodha, Dhan, Fyers, Upstox,
AliceBlue, Definedge, IndMoney, Angel One, Nubra, Arrow, IIFL Capital, Kotak),
REST-orderbook polling for brokers without push (Groww), and
`/postback/<broker>` HTTPS
webhooks on production deployments. If both a broker feed and a postback are
configured, deduplicate on `orderid` + `order_status` + `filled_quantity`.

### Heartbeat and Reconnection

* The server's WebSocket control ping interval and timeout are 20 seconds by default.
  Operators may change them with `WS_PING_INTERVAL` and `WS_PING_TIMEOUT`.
* A compliant WebSocket library automatically answers control pings with pong
  frames. The JSON `{"action":"ping"}` / `{"type":"pong"}` exchange is an
  optional application-level latency probe, not the control-frame obligation.
* After a disconnect, clients must re-authenticate and re-subscribe. A client
  library may remember its own desired subscriptions and issue them again.
* The server does not restore subscriptions for a disconnected client session;
  it removes that session's registry entries during cleanup.

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
