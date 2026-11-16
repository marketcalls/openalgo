# WebSocket Quote Feed - Integration Guide

Use the OpenAlgo WebSocket proxy for continuous market data. It shares the active broker feed with other clients. The full [wire protocol](prompt/websockets-format.md) defines authentication, acknowledgements, modes, unsubscribe results, heartbeat and reconnect behavior; [architecture](websocket-architecture.md) explains the shared feed.

## Connect and authenticate

For a local instance, connect to `ws://127.0.0.1:8765` (or the configured `WEBSOCKET_PORT`). Standard HTTPS installations reverse-proxy the feed at `wss://<your-domain>/ws`.

Send the OpenAlgo API key, not broker credentials:

```json
{"action":"authenticate","api_key":"<your_app_apikey>"}
```

A successful acknowledgement is:

```json
{
  "type": "auth",
  "status": "success",
  "message": "Authentication successful",
  "broker": "zerodha",
  "user_id": "<your_openalgo_username>",
  "supported_features": {"ltp": true, "quote": true, "depth": true}
}
```

Wait for success before subscribing. The generic `supported_features` flags do not guarantee every exchange, instrument, field or depth level is supported by the active broker; inspect subscription results and the broker capability registry.

## Subscribe and consume quotes

```json
{
  "action": "subscribe",
  "mode": "Quote",
  "symbols": [{"symbol":"RELIANCE","exchange":"NSE"}],
  "request_id": "quotes-1"
}
```

The server replies with `type: "subscribe"`, a `subscriptions` array containing each symbol's result, and `status: "success"` or `"partial"`. `partial` means at least one failure, including when all symbols fail. A successful acknowledgement does not guarantee a fresh tick has arrived.

Market values are nested inside `data`. The outbound `mode` is numeric (`1` LTP, `2` Quote, `3` Depth):

```json
{
  "type": "market_data",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "mode": 2,
  "broker": "zerodha",
  "data": {
    "ltp": 1424.0,
    "open": 1415.0,
    "high": 1432.5,
    "low": 1408.0,
    "close": 1418.0,
    "volume": 100000,
    "timestamp": 1793932200000
  }
}
```

This is an illustrative payload. Optional quote fields depend on the broker's stream and instrument; a quote is not a promise of complete OHLCV. Sahi omits OHLC and previous close because its stream does not carry them. Groww publishes fields present in its merged stream cache; many updates contain only LTP. Depth frames may include the available quote fields together with `data.depth.buy` and `data.depth.sell`; missing totals or order counts must not be inferred from one displayed level.

Use the REST [quotes](api/market-data/quotes.md) and [depth](api/market-data/depth.md) endpoints when you need one broker snapshot. REST uses `prev_close` and `bids`/`asks`; the stream normally uses `close` and `depth.buy`/`depth.sell`.

## Python SDK example

```python
import time
from openalgo import api

client = api(
    api_key="<your_app_apikey>",
    host="http://127.0.0.1:5000",
    ws_url="ws://127.0.0.1:8765",
)
instruments = [{"symbol": "RELIANCE", "exchange": "NSE"}]

def on_quote(message):
    market = message.get("data", {})
    print(message.get("symbol"), market.get("ltp"), market.get("close"))

client.connect()
try:
    client.subscribe_quote(instruments, on_data_received=on_quote)
    time.sleep(60)
finally:
    client.unsubscribe_quote(instruments)
    client.disconnect()
```

See the [Python SDK reference](<prompt/openalgo python sdk.md>) and [verbosity control](prompt/websockets-verbose-control.md). Callback payloads retain a market-data envelope; parse `message["data"]` for prices. SDK 2.0.5 fills absent Quote fields with zero defaults and retains only `ltp`/`timestamp`/`depth` in Depth callbacks. These SDK zeroes can mean unavailable; a raw WebSocket client preserves the server's field availability and extra Depth quote fields.

## Unsubscribe, reconnect, and delivery limits

Include the same mode when unsubscribing:

```json
{
  "action": "unsubscribe",
  "mode": "Quote",
  "symbols": [{"symbol":"RELIANCE","exchange":"NSE"}]
}
```

Inspect the acknowledgement's `successful` and `failed` arrays. If another client still owns the same subscription, its feed remains active. A client that reconnects must authenticate and subscribe again; the server removes disconnected-session ownership and does not replay missed ticks.

The current proxy listener forwards broker publications without an LTP time throttle. Broker publication cadence, mode fan-out, network delays and buffering still affect delivery. This feed is not a lossless exchange-tick recorder. Keep callbacks short and track data freshness in your application.

The default WebSocket control ping interval and timeout are 20 seconds (`WS_PING_INTERVAL`, `WS_PING_TIMEOUT`). A compliant library answers these automatically. Optional JSON `{"action":"ping"}` probes receive a `type: "pong"` response.

For account-level order changes, use [order updates](api/websocket-streaming/order-updates.md) with `subscribe_orders`; market-data subscriptions do not subscribe to order events.
