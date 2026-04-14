# Quote (WebSocket)

Subscribe to real-time quote updates via WebSocket including OHLC and volume data.

## WebSocket URL

```
Local Host   :  ws://127.0.0.1:8765
Custom Host  :  ws://<your-host>:8765
```

## Subscribe to Quotes

### Subscribe Message

```json
{
  "action": "subscribe",
  "mode": "quote",
  "instruments": [
    {"exchange": "NSE", "symbol": "RELIANCE"},
    {"exchange": "NSE", "symbol": "INFY"}
  ]
}
```

### Quote Update Message

```json
{
  "type": "quote",
  "data": {
    "exchange": "NSE",
    "symbol": "RELIANCE",
    "ltp": 1187.75,
    "open": 1172.0,
    "high": 1196.6,
    "low": 1163.3,
    "close": 1165.7,
    "volume": 14414545,
    "timestamp": 1712572800000
  }
}
```

## Unsubscribe from Quotes

```json
{
  "action": "unsubscribe",
  "mode": "quote",
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

# Callback for quote updates
def on_quote(data):
    print(f"Quote: {data['symbol']}")
    print(f"  LTP: {data['ltp']}")
    print(f"  High: {data['high']}, Low: {data['low']}")
    print(f"  Volume: {data['volume']}")

# Connect and subscribe
client.connect()
client.subscribe_quote(instruments, on_data_received=on_quote)

# Keep running
try:
    time.sleep(60)
finally:
    client.unsubscribe_quote(instruments)
    client.disconnect()
```

## Message Fields

### Subscribe/Unsubscribe Message

| Field | Type | Description |
|-------|------|-------------|
| action | string | "subscribe" or "unsubscribe" |
| mode | string | "quote" |
| instruments | array | Array of instrument objects |

### Quote Update Message

| Field | Type | Description |
|-------|------|-------------|
| type | string | "quote" |
| data | object | Quote data object |

### Data Object

| Field | Type | Description |
|-------|------|-------------|
| exchange | string | Exchange code |
| symbol | string | Trading symbol |
| ltp | number | Last traded price |
| open | number | Day's open price |
| high | number | Day's high price |
| low | number | Day's low price |
| close | number | Previous close price |
| volume | number | Total traded volume |
| timestamp | number | Update time (epoch ms) |

## Notes

- Quote mode provides **OHLCV data** in addition to LTP
- Updates are less frequent than LTP (on significant changes)
- Use for:
  - Market overview displays
  - Technical analysis
  - Charting applications

## Related Endpoints

- [LTP WebSocket](./ltp.md) - Minimal data, lowest latency
- [Depth WebSocket](./depth.md) - Full market depth

---

**Back to**: [API Documentation](../README.md)
