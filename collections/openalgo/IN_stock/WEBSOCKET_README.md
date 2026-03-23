# OpenAlgo WebSocket API Templates

This folder contains Bruno-style templates for WebSocket message formats.

## Connection

WebSocket URL is configured in `.env`:
```
WEBSOCKET_HOST='127.0.0.1'
WEBSOCKET_PORT='8765'
WEBSOCKET_URL='ws://127.0.0.1:8765'
```

## Authentication Flow

1. Connect to WebSocket server
2. Send `authenticate` message with API key
3. Wait for `auth` response with `status: success`
4. Subscribe to market data

## Message Modes

| Mode | Name | Description | Data Returned |
|------|------|-------------|---------------|
| 1 | LTP | Last Traded Price | ltp, timestamp |
| 2 | Quote | Full Quote | ltp, open, high, low, close, volume, change |
| 3 | Depth | Market Depth | ltp + bid/ask levels |

## Depth Levels

For Mode 3 (Depth), you can specify `depth` parameter:
- `5` - 5 bid/ask levels (default)
- `20` - 20 bid/ask levels
- `30` - 30 bid/ask levels (broker dependent)
- `50` - 50 bid/ask levels (broker dependent)

## Message Formats

### Single Symbol Format
```json
{
  "action": "subscribe",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "mode": 1
}
```

### Array Format (Multiple Symbols)
```json
{
  "action": "subscribe",
  "symbols": [
    {"symbol": "RELIANCE", "exchange": "NSE"},
    {"symbol": "TCS", "exchange": "NSE"}
  ],
  "mode": 1
}
```

### Mode as String
```json
{
  "action": "subscribe",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "mode": "LTP"
}
```

Valid string modes: `"LTP"`, `"Quote"`, `"Depth"`

## Template Files

| File | Action | Description |
|------|--------|-------------|
| ws_authenticate.bru | authenticate | Authenticate with API key |
| ws_subscribe_ltp.bru | subscribe | Subscribe to LTP (Mode 1) |
| ws_subscribe_quote.bru | subscribe | Subscribe to Quote (Mode 2) |
| ws_subscribe_depth_5.bru | subscribe | Subscribe to Depth 5 levels |
| ws_subscribe_depth_20.bru | subscribe | Subscribe to Depth 20 levels |
| ws_subscribe_depth_30.bru | subscribe | Subscribe to Depth 30 levels |
| ws_subscribe_depth_50.bru | subscribe | Subscribe to Depth 50 levels |
| ws_subscribe_multiple.bru | subscribe | Subscribe multiple symbols |
| ws_unsubscribe.bru | unsubscribe | Unsubscribe from symbol |
| ws_unsubscribe_all.bru | unsubscribe_all | Unsubscribe from all |
| ws_get_broker_info.bru | get_broker_info | Get broker information |
| ws_get_supported_brokers.bru | get_supported_brokers | List supported brokers |
| ws_ping.bru | ping | Test connection latency |

## Supported Exchanges

- NSE - National Stock Exchange
- NFO - NSE Futures & Options
- BSE - Bombay Stock Exchange
- BFO - BSE Futures & Options
- CDS - Currency Derivatives
- MCX - Multi Commodity Exchange

## Limits

- Max symbols per connection: 1000 (configurable)
- Max connections: 3 (configurable)
- Total capacity: 3000 symbols
