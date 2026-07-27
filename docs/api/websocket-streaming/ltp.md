# LTP (WebSocket)

Subscribe to real-time Last Traded Price (LTP) updates via WebSocket.

## WebSocket URL

```
Local Host   :  ws://127.0.0.1:8765
Custom Host  :  ws://<your-host>:8765
```

## Subscribe to LTP

### Subscribe Message

```json
{
  "action": "subscribe",
  "mode": "ltp",
  "instruments": [
    {"exchange": "NSE", "symbol": "RELIANCE"},
    {"exchange": "NSE", "symbol": "INFY"}
  ]
}
```

### LTP Update Message

```json
{
  "type": "ltp",
  "data": {
    "exchange": "NSE",
    "symbol": "RELIANCE",
    "ltp": 1187.75,
    "timestamp": 1712572800000
  }
}
```

## Unsubscribe from LTP

```json
{
  "action": "unsubscribe",
  "mode": "ltp",
  "instruments": [
    {"exchange": "NSE", "symbol": "RELIANCE"}
  ]
}
```

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
| mode | string | "ltp" |
| instruments | array | Array of instrument objects |

### Instrument Object

| Field | Type | Description |
|-------|------|-------------|
| exchange | string | Exchange code (NSE, BSE, NFO, etc.) |
| symbol | string | Trading symbol |

### LTP Update Message

| Field | Type | Description |
|-------|------|-------------|
| type | string | "ltp" |
| data | object | LTP data object |

### Data Object

| Field | Type | Description |
|-------|------|-------------|
| exchange | string | Exchange code |
| symbol | string | Trading symbol |
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
