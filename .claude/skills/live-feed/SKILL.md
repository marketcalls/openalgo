---
name: live-feed
description: Set up real-time indicator computation on live WebSocket market data. Streams LTP/Quote/Depth and computes indicators in real-time with optional Plotly live charting.
argument-hint: "[symbol] [exchange] [mode]"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, AskUserQuestion
---

Create a real-time indicator feed using OpenAlgo WebSocket streaming.

## Arguments

Parse `$ARGUMENTS` as: symbol exchange mode

- `$0` = symbol (e.g., SBIN, RELIANCE, NIFTY). Default: SBIN
- `$1` = exchange (e.g., NSE, NSE_INDEX). Default: NSE
- `$2` = mode (e.g., ltp, quote, depth, multi). Default: quote

If no arguments, ask user for symbol and what data they want.

## Instructions

1. Read the indicator-expert rules, especially:
   - `rules/websocket-feeds.md` — WebSocket connection and subscription
   - `rules/data-fetching.md` — Historical data for buffer initialization
2. Create `charts/live/` directory (on-demand)
3. Create `{symbol}_live_feed.py`
4. Use the template from `rules/assets/live_feed/template.py`

### Feed Types

#### `ltp` — Last Traded Price + Indicators
- Subscribe to LTP feed
- Maintain rolling buffer (last 200 ticks)
- Compute EMA, RSI on buffer
- Print real-time indicator values

#### `quote` — Full Quote + Indicators
- Subscribe to Quote feed
- Display OHLC + LTP + Volume
- Compute indicators on close buffer
- Color-coded output (bullish/bearish)

#### `depth` — Market Depth Analysis
- Subscribe to Depth feed
- Display L5 bid/ask book
- Compute bid-ask spread, order imbalance
- Show total buy vs sell quantity

#### `multi` — Multi-Symbol Feed
- Subscribe to multiple symbols
- Display watchlist table with LTP and key indicator
- Auto-refresh display

### Script Structure

```python
"""
Real-Time Indicator Feed for {SYMBOL}
Mode: {mode}
"""
import os
import time
import numpy as np
from datetime import datetime, timedelta
from dotenv import find_dotenv, load_dotenv
from openalgo import api, ta

load_dotenv(find_dotenv(), override=False)

SYMBOL = "{symbol}"
EXCHANGE = "{exchange}"

client = api(
    api_key=os.getenv("OPENALGO_API_KEY"),
    host=os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000"),
    verbose=1,
)

# Pre-fetch historical data for buffer initialization
df = client.history(
    symbol=SYMBOL, exchange=EXCHANGE, interval="1m",
    start_date=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
    end_date=datetime.now().strftime("%Y-%m-%d"),
)
close_buffer = list(df["close"].values[-200:])

instruments = [{"exchange": EXCHANGE, "symbol": SYMBOL}]

def on_data(data):
    ltp = data["data"].get("ltp")
    if ltp is None:
        return

    close_buffer.append(float(ltp))
    if len(close_buffer) > 200:
        close_buffer.pop(0)

    if len(close_buffer) >= 20:
        arr = np.array(close_buffer, dtype=np.float64)
        ema_val = ta.ema(arr, 20)[-1]
        rsi_val = ta.rsi(arr, 14)[-1] if len(arr) >= 15 else float("nan")

        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {SYMBOL} LTP:{ltp:>10.2f} | "
              f"EMA(20):{ema_val:>10.2f} | RSI(14):{rsi_val:>6.2f}")

# Connect and subscribe
client.connect()
client.subscribe_ltp(instruments, on_data_received=on_data)

print(f"Streaming {SYMBOL} on {EXCHANGE} — Press Ctrl+C to stop")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("Stopping feed...")

client.unsubscribe_ltp(instruments)
client.disconnect()
```

### Cleanup

The script must:
- Handle Ctrl+C gracefully
- Unsubscribe from all feeds
- Disconnect WebSocket
- Print summary of session duration and bars processed

## Verbose Levels

Inform user about verbose options:
- `verbose=0`: Silent mode (errors only)
- `verbose=1`: Connection and subscription logs
- `verbose=2`: All data updates (debug mode)

## Example Usage

`/live-feed SBIN NSE ltp`
`/live-feed NIFTY NSE_INDEX quote`
`/live-feed SBIN NSE depth`
`/live-feed multi NSE`
