# Depth (WebSocket)

Subscribe to real-time market depth (Level 2) updates via WebSocket.

## WebSocket URL

```
Local Host   :  ws://127.0.0.1:8765
Custom Host  :  ws://<your-host>:8765
```

## WebSocket Request

```json
{
  "action": "subscribe",
  "mode": "Depth",
  "depth": 5,
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
  "mode": 3,
  "broker": "zerodha",
  "data": {
    "ltp": 1187.75,
    "ltq": 100,
    "open": 1172.0,
    "high": 1196.6,
    "low": 1163.3,
    "close": 1165.7,
    "volume": 14414545,
    "totalbuyqty": 591351,
    "totalsellqty": 835701,
    "depth": {
      "buy": [
        {"price": 1187.70, "quantity": 886, "orders": 4},
        {"price": 1187.65, "quantity": 212, "orders": 2},
        {"price": 1187.60, "quantity": 351, "orders": 3},
        {"price": 1187.55, "quantity": 343, "orders": 5},
        {"price": 1187.50, "quantity": 399, "orders": 2}
      ],
      "sell": [
        {"price": 1187.80, "quantity": 767, "orders": 3},
        {"price": 1187.85, "quantity": 115, "orders": 1},
        {"price": 1187.90, "quantity": 162, "orders": 2},
        {"price": 1187.95, "quantity": 1121, "orders": 6},
        {"price": 1188.00, "quantity": 430, "orders": 2}
      ]
    },
    "timestamp": 1712572800000
  }
}
```

## Unsubscribe from Depth

```json
{
  "action": "unsubscribe",
  "mode": "Depth",
  "symbols": [
    {"exchange": "NSE", "symbol": "RELIANCE"}
  ]
}
```

The unsubscribe acknowledgement lists exact outcomes in `successful` and
`failed`. Mode-valid acknowledgement items carry the canonical `mode` value
`"Depth"`; when mode validation itself fails, `mode` is `null`. A broker
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

# Callback for depth updates
def on_depth(data):
    print(f"Depth: {data['symbol']}")
    market = data['data']
    print(f"  LTP: {market['ltp']}")
    print(f"  Best Bid: {market['depth']['buy'][0]['price']} x {market['depth']['buy'][0]['quantity']}")
    print(f"  Best Ask: {market['depth']['sell'][0]['price']} x {market['depth']['sell'][0]['quantity']}")
    print(f"  Total Buy Qty: {market['totalbuyqty']}")
    print(f"  Total Sell Qty: {market['totalsellqty']}")

# Connect and subscribe
client.connect()
client.subscribe_depth(instruments, on_data_received=on_depth)

# Keep running
try:
    time.sleep(60)
finally:
    client.unsubscribe_depth(instruments)
    client.disconnect()
```

## Message Fields

### Subscribe/Unsubscribe Message

| Field | Type | Description |
|-------|------|-------------|
| action | string | "subscribe" or "unsubscribe" |
| mode | integer or string | `3` or case-insensitive `Depth` |
| depth | integer | Requested levels, default `5`; broker capability decides the supported maximum |
| symbols | array | Array of symbol/exchange objects. Singular `symbol` plus `exchange` is a compatibility alias |

### Market Data Update Message

| Field | Type | Description |
|-------|------|-------------|
| type | string | Always `market_data` |
| symbol | string | Trading symbol |
| exchange | string | Exchange code |
| mode | integer | Numeric subscribed mode (`3`) |
| broker | string | Broker that supplied the frame |
| data | object | Depth data object |

### Data Object

| Field | Type | Description |
|-------|------|-------------|
| ltp | number | Last traded price |
| ltq | number | Last traded quantity |
| open | number | Day's open price |
| high | number | Day's high price |
| low | number | Day's low price |
| close | number | Previous close price |
| volume | number | Total traded volume |
| totalbuyqty | number | Total buy quantity in order book |
| totalsellqty | number | Total sell quantity in order book |
| depth | object | Order book with `buy` and `sell` arrays |
| timestamp | number | Update time (epoch ms) |

### Depth Object

| Field | Type | Description |
|-------|------|-------------|
| buy | array | Bid levels, best price first |
| sell | array | Ask levels, best price first |

### Buy/Sell Level Object

| Field | Type | Description |
|-------|------|-------------|
| price | number | Price level |
| quantity | number | Quantity at this level |
| orders | number | Order count at this level when supplied by the broker |

## Notes

- Depth mode provides the requested number of order-book levels when the
  broker supports it; `5` is the default
- Highest bandwidth consumption among streaming modes
- Updates on every order book change
- Use for:
  - Scalping strategies
  - Order flow analysis
  - Liquidity monitoring
  - Smart order routing

## Related Endpoints

- [LTP WebSocket](./ltp.md) - Minimal data, lowest latency
- [Quote WebSocket](./quote.md) - OHLCV data

---

**Back to**: [API Documentation](../README.md)
