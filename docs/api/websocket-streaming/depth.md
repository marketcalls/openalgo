# Depth (WebSocket)

Subscribe to real-time market depth (Level 2) updates via WebSocket.

## WebSocket URL

```
Local Host   :  ws://127.0.0.1:8765
Custom Host  :  ws://<your-host>:8765
```

## Subscribe to Depth

### Subscribe Message

```json
{
  "action": "subscribe",
  "mode": "depth",
  "instruments": [
    {"exchange": "NSE", "symbol": "RELIANCE"},
    {"exchange": "NSE", "symbol": "INFY"}
  ]
}
```

### Depth Update Message

```json
{
  "type": "depth",
  "data": {
    "exchange": "NSE",
    "symbol": "RELIANCE",
    "ltp": 1187.75,
    "ltq": 100,
    "open": 1172.0,
    "high": 1196.6,
    "low": 1163.3,
    "close": 1165.7,
    "volume": 14414545,
    "totalbuyqty": 591351,
    "totalsellqty": 835701,
    "bids": [
      {"price": 1187.70, "quantity": 886},
      {"price": 1187.65, "quantity": 212},
      {"price": 1187.60, "quantity": 351},
      {"price": 1187.55, "quantity": 343},
      {"price": 1187.50, "quantity": 399}
    ],
    "asks": [
      {"price": 1187.80, "quantity": 767},
      {"price": 1187.85, "quantity": 115},
      {"price": 1187.90, "quantity": 162},
      {"price": 1187.95, "quantity": 1121},
      {"price": 1188.00, "quantity": 430}
    ],
    "timestamp": 1712572800000
  }
}
```

## Unsubscribe from Depth

```json
{
  "action": "unsubscribe",
  "mode": "depth",
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

# Callback for depth updates
def on_depth(data):
    print(f"Depth: {data['symbol']}")
    print(f"  LTP: {data['ltp']}")
    print(f"  Best Bid: {data['bids'][0]['price']} x {data['bids'][0]['quantity']}")
    print(f"  Best Ask: {data['asks'][0]['price']} x {data['asks'][0]['quantity']}")
    print(f"  Total Buy Qty: {data['totalbuyqty']}")
    print(f"  Total Sell Qty: {data['totalsellqty']}")

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
| mode | string | "depth" |
| instruments | array | Array of instrument objects |

### Depth Update Message

| Field | Type | Description |
|-------|------|-------------|
| type | string | "depth" |
| data | object | Depth data object |

### Data Object

| Field | Type | Description |
|-------|------|-------------|
| exchange | string | Exchange code |
| symbol | string | Trading symbol |
| ltp | number | Last traded price |
| ltq | number | Last traded quantity |
| open | number | Day's open price |
| high | number | Day's high price |
| low | number | Day's low price |
| close | number | Previous close price |
| volume | number | Total traded volume |
| totalbuyqty | number | Total buy quantity in order book |
| totalsellqty | number | Total sell quantity in order book |
| bids | array | Top 5 bid levels |
| asks | array | Top 5 ask levels |
| timestamp | number | Update time (epoch ms) |

### Bid/Ask Object

| Field | Type | Description |
|-------|------|-------------|
| price | number | Price level |
| quantity | number | Quantity at this level |

## Notes

- Depth mode provides **full order book** data (top 5 levels)
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
