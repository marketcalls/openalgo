# WebSocket Feeds — Real-Time Data

## Overview

OpenAlgo provides WebSocket streaming for real-time market data. Three subscription modes:

| Mode | Method | Data Fields |
|------|--------|------------|
| **LTP** | `subscribe_ltp()` | Last traded price only |
| **Quote** | `subscribe_quote()` | OHLC + LTP + volume |
| **Depth** | `subscribe_depth()` | Full L5 order book |

## Connection Setup

```python
from openalgo import api
import os
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(), override=False)

client = api(
    api_key=os.getenv("OPENALGO_API_KEY"),
    host=os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000"),
    ws_url=os.getenv("OPENALGO_WS_URL", None),  # Optional: custom WS URL
    verbose=1,  # 0=silent, 1=basic, 2=debug
)

# Connect to WebSocket server
client.connect()
```

## Verbose Levels

| Level | Value | Description |
|-------|-------|-------------|
| Silent | `False` or `0` | Errors only (default) |
| Basic | `True` or `1` | Connection, auth, subscription logs |
| Debug | `2` | All data updates including LTP/Quote/Depth |

---

## LTP Subscription

```python
instruments = [
    {"exchange": "NSE", "symbol": "SBIN"},
    {"exchange": "NSE", "symbol": "RELIANCE"},
    {"exchange": "NSE_INDEX", "symbol": "NIFTY"},
]

def on_ltp(data):
    symbol = data["symbol"]
    ltp = data["data"].get("ltp")
    print(f"{symbol}: {ltp}")

client.subscribe_ltp(instruments, on_data_received=on_ltp)
```

## Quote Subscription

```python
def on_quote(data):
    symbol = data["symbol"]
    d = data["data"]
    print(f"{symbol} O:{d.get('open')} H:{d.get('high')} L:{d.get('low')} LTP:{d.get('ltp')} V:{d.get('volume')}")

client.subscribe_quote(instruments, on_data_received=on_quote)
```

## Depth Subscription

```python
def on_depth(data):
    symbol = data["symbol"]
    d = data["data"]
    best_bid = d.get("bids", [{}])[0].get("price", 0)
    best_ask = d.get("asks", [{}])[0].get("price", 0)
    spread = best_ask - best_bid
    print(f"{symbol} Bid:{best_bid} Ask:{best_ask} Spread:{spread:.2f}")

client.subscribe_depth(instruments, on_data_received=on_depth)
```

## Polling Stored Data

After subscribing, data is stored internally and can be polled:

```python
import time

for _ in range(10):
    # Get latest LTP data
    ltp_data = client.get_ltp()
    for exch, symbols in ltp_data.get("ltp", {}).items():
        for sym, data in symbols.items():
            print(f"  {exch}:{sym} = {data.get('ltp')}")

    # Get latest quotes
    quote_data = client.get_quotes()
    for exch, symbols in quote_data.get("quote", {}).items():
        for sym, data in symbols.items():
            print(f"  {exch}:{sym} LTP={data.get('ltp')} V={data.get('volume')}")

    time.sleep(1)
```

## Unsubscribe and Disconnect

```python
# Unsubscribe specific instruments
client.unsubscribe_ltp(instruments)
client.unsubscribe_quote(instruments)
client.unsubscribe_depth(instruments)

# Disconnect WebSocket
client.disconnect()
```

---

## Real-Time Indicator Pattern

Compute indicators on live data by maintaining a rolling buffer:

```python
import numpy as np
from openalgo import ta
import time

# Pre-fetch historical data for initial buffer
df = client.history(symbol="SBIN", exchange="NSE", interval="1m",
                    start_date="2025-02-28", end_date="2025-02-28")
close_buffer = list(df["close"].values)

instruments = [{"exchange": "NSE", "symbol": "SBIN"}]

def on_live_data(data):
    ltp = data["data"].get("ltp")
    if ltp is None:
        return

    close_buffer.append(float(ltp))

    # Keep last 200 bars
    if len(close_buffer) > 200:
        close_buffer.pop(0)

    if len(close_buffer) >= 20:
        arr = np.array(close_buffer, dtype=np.float64)
        ema_val = ta.ema(arr, 20)[-1]
        rsi_val = ta.rsi(arr, 14)[-1]
        print(f"SBIN LTP:{ltp} EMA(20):{ema_val:.2f} RSI(14):{rsi_val:.2f}")

client.connect()
client.subscribe_ltp(instruments, on_data_received=on_live_data)

# Run for 60 seconds
time.sleep(60)

client.unsubscribe_ltp(instruments)
client.disconnect()
```

---

## WebSocket Log Tags

| Tag | Meaning |
|-----|---------|
| `[WS]` | Connection events |
| `[AUTH]` | Authentication |
| `[SUB]` | Subscription operations |
| `[UNSUB]` | Unsubscription |
| `[LTP]` | LTP updates (verbose=2) |
| `[QUOTE]` | Quote updates (verbose=2) |
| `[DEPTH]` | Depth updates (verbose=2) |
| `[ERROR]` | Errors (always shown) |
