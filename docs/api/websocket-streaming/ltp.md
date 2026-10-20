# LTP (WebSocket)

Subscribe to real-time Last Traded Price (LTP) updates via WebSocket.

## WebSocket URL

```
Local Host   :  ws://127.0.0.1:8765
Custom Host  :  ws://<your-host>:8765
```

## WebSocket Request

```json
{
  "action": "subscribe",
  "mode": "LTP",
  "symbols": [
    {"exchange": "NSE", "symbol": "RELIANCE"},
    {"exchange": "NSE", "symbol": "INFY"}
  ]
}
```

## Sample Response

```json
{
  "type": "market_data",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "mode": 1,
  "broker": "zerodha",
  "data": {
    "ltp": 1187.75,
    "timestamp": 1712572800000
  }
}
```

## Unsubscribe from LTP

```json
{
  "action": "unsubscribe",
  "mode": "LTP",
  "symbols": [
    {"exchange": "NSE", "symbol": "RELIANCE"}
  ]
}
```

The unsubscribe acknowledgement lists exact outcomes in `successful` and
`failed`. Mode-valid acknowledgement items carry the canonical `mode` value
`"LTP"`; when mode validation itself fails, `mode` is `null`. A broker refusal
leaves the final local owner registered so the request can be retried.
Disconnect cleanup does not retain a dead client owner; any unresolved feed is
reclaimed by the user's last-client adapter teardown.

## Python SDK Example

```python
from openalgo import api
import time

# Initialize client with WebSocket
client = api(
    api_key="your_api_key",
    host="http://127.0.0.1:5000",
    ws_url="ws://127.0.0.1:8765"
)

# Instruments to subscribe
instruments = [
    {"exchange": "NSE", "symbol": "RELIANCE"},
    {"exchange": "NSE", "symbol": "INFY"}
]

# Callback for LTP updates
def on_ltp(data):
    print(f"LTP Update: {data['symbol']} = {data['ltp']}")

# Connect and subscribe
client.connect()
client.subscribe_ltp(instruments, on_data_received=on_ltp)

# Keep running
try:
    time.sleep(60)  # Run for 60 seconds
finally:
    client.unsubscribe_ltp(instruments)
    client.disconnect()
```

## Message Fields

### Subscribe/Unsubscribe Message

| Field | Type | Description |
|-------|------|-------------|
| action | string | "subscribe" or "unsubscribe" |
| mode | integer or string | `1` or case-insensitive `LTP` |
| symbols | array | Array of symbol/exchange objects. Singular `symbol` plus `exchange` is a compatibility alias |

### Instrument Object

| Field | Type | Description |
|-------|------|-------------|
| exchange | string | Exchange code (NSE, BSE, NFO, etc.) |
| symbol | string | Trading symbol |

### Market Data Update Message

| Field | Type | Description |
|-------|------|-------------|
| type | string | Always `market_data` |
| symbol | string | Trading symbol |
| exchange | string | Exchange code |
| mode | integer | Numeric subscribed mode (`1`) |
| broker | string | Broker that supplied the frame |
| data | object | LTP data object |

### Data Object

| Field | Type | Description |
|-------|------|-------------|
| ltp | number | Last traded price |
| timestamp | number | Update time (epoch milliseconds) |

## Notes

- LTP mode provides **minimal data** for lowest latency
- Updates are pushed **on every tick** (each trade)
- Subscribe to multiple symbols in a single message
- Use for:
  - Price displays
  - Trigger-based alerts
  - Simple strategy signals

## Related Endpoints

- [Quote WebSocket](./quote.md) - More data including OHLC
- [Depth WebSocket](./depth.md) - Full market depth

---

**Back to**: [API Documentation](../README.md)
