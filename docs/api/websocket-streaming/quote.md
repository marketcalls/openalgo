# Quote (WebSocket)

Subscribe to real-time quote updates via WebSocket including OHLC and volume data.

## WebSocket URL

```
Local Host   :  ws://127.0.0.1:8765
Custom Host  :  ws://<your-host>:8765
```

## WebSocket Request

```json
{
  "action": "subscribe",
  "mode": "Quote",
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
  "mode": 2,
  "broker": "zerodha",
  "data": {
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
  "mode": "Quote",
  "symbols": [
    {"exchange": "NSE", "symbol": "RELIANCE"}
  ]
}
```

The unsubscribe acknowledgement lists exact outcomes in `successful` and
`failed`. Mode-valid acknowledgement items carry the canonical `mode` value
`"Quote"`; when mode validation itself fails, `mode` is `null`. A broker
refusal leaves the final local owner registered so the request can be retried.
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

# Callback for quote updates
def on_quote(data):
    print(f"Quote: {data['symbol']}")
    market = data["data"]
    print(f"  LTP: {market.get('ltp')}")
    # SDK 2.0.5 fills absent raw quote fields with zero defaults
    print(f"  High: {market.get('high')}, Low: {market.get('low')}")
    print(f"  Volume: {market.get('volume')}")

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
| mode | integer or string | `2` or case-insensitive `Quote` |
| symbols | array | Array of symbol/exchange objects. Singular `symbol` plus `exchange` is a compatibility alias |

### Market Data Update Message

| Field | Type | Description |
|-------|------|-------------|
| type | string | Always `market_data` |
| symbol | string | Trading symbol |
| exchange | string | Exchange code |
| mode | integer | Numeric subscribed mode (`2`) |
| broker | string | Broker that supplied the frame |
| data | object | Quote data object |

### Data Object

| Field | Type | Description |
|-------|------|-------------|
| ltp | number | Last traded price |
| open | number | Day's open price (absent when the broker's feed does not carry it) |
| high | number | Day's high price (absent when the broker's feed does not carry it) |
| low | number | Day's low price (absent when the broker's feed does not carry it) |
| close | number | Previous close price (absent when the broker's feed does not carry it) |
| volume | number | Total traded volume |
| timestamp | number | Update time (epoch ms) |

## Notes

- Quote mode provides **OHLCV data** in addition to LTP, where the broker's feed carries it
- Raw frame field availability depends on the broker. Sahi omits open/high/low/previous close, and Groww publishes available fields from its merged cache, commonly only LTP. Do not treat a missing value as a measured zero
- Python SDK 2.0.5 fills a fixed Quote field set with zero defaults and passes it under callback `data["data"]`; these zeroes can mean unavailable. Use raw frames when you need to preserve missing-field semantics
- Update cadence depends on the broker; there is no universal ordering or frequency guarantee between Quote and LTP
- Use for:
  - Market overview displays
  - Technical analysis
  - Charting applications

## Related Endpoints

- [LTP WebSocket](./ltp.md) - Minimal data, lowest latency
- [Depth WebSocket](./depth.md) - Full market depth

---

**Back to**: [API Documentation](../README.md)
