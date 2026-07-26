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
2. Create `workspace/indicators/feeds/` (`mkdir -p`)
3. Write the script to `workspace/indicators/feeds/{mode}_{symbol}.py`
4. Use the template from `rules/assets/live_feed/template.py`

### Feed Types

#### `ltp` — Last Traded Price + Indicators
- Subscribe to LTP feed
- Maintain rolling buffer (last 200 ticks)
- Compute EMA, RSI on buffer
- Print real-time indicator values

**These are tick-window values, not bar values.** An EMA over 200 ticks is not
EMA(20) on a chart and must not be compared to one. Label the output
accordingly, and see the verification section before using any of it for
trading logic.

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

## Verify before calling it done

A live feed can look healthy while delivering nothing. Check all six:

- [ ] **Ticks actually arrive.** Count messages over 60 seconds during market hours. Zero ticks with a connected socket is the classic symptom of subscribing to the wrong exchange for the symbol type — index underlyings need `NSE_INDEX`/`BSE_INDEX`, stocks need `NSE`/`BSE`.
- [ ] **Values are plausible.** Compare a streamed LTP against `/api/v1/quotes` for the same symbol. A price off by 100x is a paise-scaling bug; a "close" that matches the last traded quantity is a binary-offset bug in the broker adapter.
- [ ] **Reconnect works.** Kill the network for 30 seconds and confirm the client reconnects, re-authenticates and re-subscribes. Subscriptions are not automatically restored by every path, so an apparently-recovered connection can be silently dead.
- [ ] **Indicator state survives a gap.** After a reconnect, a rolling indicator must not treat the gap as contiguous bars. Either backfill from history or reset the window.
- [ ] **Cleanup releases everything.** On Ctrl-C, confirm the socket closes and any subscription is cancelled. Long-running feeds are the most common source of descriptor leaks; the `fd-audit` skill covers the audit, and `soak.py` measures it.
- [ ] **Outside market hours, absence of ticks is expected.** Do not debug a "broken" feed at 21:00 IST. Confirm against `/api/v1/quotes` returning a stale-but-valid last close.

**Tick-window indicators are not bar indicators — label them as such.** The
`ltp` template deliberately keeps a rolling buffer of the last 200 *ticks* and
recomputes on each one. That is a legitimate design for a live monitor, but
`ta.ema(ticks, 20)` is an EMA over 20 trades, not over 20 bars, and it will not
match any chart. Never compare the two, and never feed a tick-window value into
logic that assumes bar semantics.

If you need bar semantics — anything a strategy or a chart will act on —
aggregate ticks into interval bars first and compute on bar closes.

Either way, recomputing the full buffer on every tick is O(buffer) per tick and
becomes a CPU sink above a few hundred ticks/second. Throttle to every Nth tick
or to a wall-clock interval once the feed is busy.

## Where to write files

Default location is **`workspace/indicators/feeds/`** in the repo root. Create it
immediately before writing — it does not exist on a fresh clone:

```bash
mkdir -p workspace/indicators/feeds
```

Name the file `<indicator>_<symbol>_<interval>.py` so the folder stays
scannable as it grows, e.g. `workspace/indicators/feeds/ltp_SBIN.py`.

**If the user names a different folder, use it** and keep the same layout
beneath it. Note that only `workspace/` is gitignored (except its readme), so
writing elsewhere inside the repo produces tracked files — mention that before
doing it.

Run from the repo root:

```bash
uv run --group analysis python workspace/indicators/feeds/ltp_SBIN.py
```
