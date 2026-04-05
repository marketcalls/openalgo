# OpenAlgo Real-Time Scanner Service — Architecture & Implementation Guide

## Overview

A standalone, external scanner service that monitors 500+ symbols in real-time on any timeframe, running multiple independent scanners (RSI, EMA crossover, volume spike, custom conditions) without hitting broker API rate limits.

The service builds candles from OpenAlgo's live WebSocket tick stream, bootstraps indicator state from Historify (DuckDB) at startup, and distributes candle events to multiple scanner processes via Redis Streams.

---

## Problem Statement

Most Indian brokers restrict historical data API calls to 1-10 requests per second. Scanning 500 symbols by polling the REST API is fundamentally broken:

- 500 symbols at 10 req/sec = 50 seconds per scan cycle
- Data is stale before the scan completes
- Repeated polling wastes API quota
- Cannot scale beyond ~10 symbols in real-time

**Solution:** Eliminate the REST API from the real-time path entirely. Use the broker WebSocket (no rate limits) for live ticks, and local DuckDB (no rate limits) for historical bootstrap.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         PRE-MARKET BOOTSTRAP                        │
│                                                                     │
│  Historify (DuckDB) — stores 1m candle history for all symbols      │
│  └── OpenAlgo API: GET /history (source="Db", interval="1m")        │
│      └── Fetch last N 1-minute candles per symbol                   │
│      └── Local database — zero rate limits, completes in seconds    │
│      └── Seeds indicator state so scanners are ready at 9:15 AM     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ indicators initialized
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         REAL-TIME TICK LAYER                        │
│                                                                     │
│  OpenAlgo WebSocket Proxy (port 8765)                               │
│  └── Authenticate with API key                                     │
│  └── Subscribe to 500+ symbols in LTP or Quote mode                │
│  └── Receive ~500-2000 ticks/second                                │
│  └── No rate limits — broker WebSocket is unlimited                 │
│                                                                     │
│  Tick Receiver Process                                              │
│  └── Single async WebSocket client                                  │
│  └── Publishes every tick to Redis Stream: ticks:raw                │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         CANDLE BUILDER                              │
│                                                                     │
│  Single Python Process                                              │
│  └── Consumes ticks from Redis Stream: ticks:raw                    │
│  └── Maintains in-memory candle state for all symbols               │
│  └── On minute boundary:                                            │
│       ├── Closes current candle                                     │
│       ├── Appends to rolling window (per symbol)                    │
│       ├── Publishes completed candle to Redis Stream: candles:1m    │
│       └── Optionally builds higher timeframes (5m, 15m)             │
│                                                                     │
│  Memory: 500 symbols x 200 candles x ~100 bytes = ~10 MB           │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
              ┌────────────────┼────────────────┬──────────────┐
              ▼                ▼                ▼              ▼
┌───────────────────┐ ┌───────────────┐ ┌───────────────┐ ┌──────────────┐
│   Scanner #1      │ │  Scanner #2   │ │  Scanner #3   │ │  Scanner #N  │
│   RSI > 70        │ │  EMA Cross    │ │  Vol Spike    │ │  Custom      │
│                   │ │               │ │               │ │              │
│ Consumer group:   │ │ Consumer grp: │ │ Consumer grp: │ │ Consumer grp:│
│ scanner_rsi       │ │ scanner_ema   │ │ scanner_vol   │ │ scanner_N    │
│                   │ │               │ │               │ │              │
│ Reads: candles:1m │ │ candles:1m    │ │ candles:1m    │ │ candles:1m   │
│ Maintains own     │ │ Maintains own │ │ Maintains own │ │ Maintains own│
│ indicator state   │ │ indicator     │ │ indicator     │ │ indicator    │
│ per symbol        │ │ state         │ │ state         │ │ state        │
│                   │ │               │ │               │ │              │
│ Emits → alerts    │ │ Emits → alerts│ │ Emits → alerts│ │ Emits→alerts │
└─────────┬─────────┘ └──────┬────────┘ └──────┬────────┘ └──────┬──────┘
          └──────────────────┴─────────────────┴─────────────────┘
                                    │
                                    ▼
                    ┌──────────────────────────────┐
                    │       Results Aggregator      │
                    │                               │
                    │  Redis Stream: alerts          │
                    │  └── Dashboard WebSocket       │
                    │  └── Webhook notifications     │
                    │  └── OpenAlgo PlaceOrder API   │
                    │  └── Telegram / Discord bot    │
                    └──────────────────────────────┘
                                    │
                                    ▼ (at market close)
                    ┌──────────────────────────────┐
                    │     End-of-Day Persistence     │
                    │                               │
                    │  Write all 1m candles built    │
                    │  today back to Historify       │
                    │  (via OpenAlgo API or direct   │
                    │   DuckDB write)                │
                    │                               │
                    │  Next morning's bootstrap      │
                    │  uses today's stored candles   │
                    └──────────────────────────────┘
```

---

## Component Details

### 1. Tick Receiver

**Purpose:** Single point of connection to OpenAlgo WebSocket. Receives all ticks and publishes to Redis for downstream consumption.

**Why a separate process:** Isolates the WebSocket connection from processing logic. If a scanner crashes or the candle builder stalls, the tick receiver keeps running and buffering into Redis. No ticks are lost.

**Connection details:**
- WebSocket URL: `ws://127.0.0.1:8765`
- Authentication: `{"action": "authenticate", "apikey": "<OPENALGO_API_KEY>"}`
- Subscribe: `{"action": "subscribe", "symbols": [{"symbol": "RELIANCE", "exchange": "NSE"}, ...], "mode": "LTP"}`
- Incoming message format: `{"type": "market_data", "symbol": "RELIANCE", "exchange": "NSE", "mode": 1, "data": {"ltp": 2543.50, "volume": 1000000, ...}}`

**Redis Stream output:**
```
Stream: ticks:raw
Entry: {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "ltp": "2543.50",
    "volume": "1000000",
    "timestamp": "1712200000000"
}
```

**Subscription strategy:**
- OpenAlgo supports up to 3000 symbols via connection pooling (3 connections x 1000 symbols each)
- Subscribe in batches of 50-100 symbols to avoid overwhelming the initial connection
- Use LTP mode for most scanners (lowest bandwidth). Use Quote mode only if scanners need bid/ask/open/high/low/close fields

**Symbol list management:**
- Load symbol list from a config file (`symbols.json` or `symbols.csv`)
- Support hot-reload: watch the file for changes, subscribe/unsubscribe dynamically
- Group symbols by exchange (NSE, NFO, BSE) for organized subscription

---

### 2. Candle Builder

**Purpose:** Consumes raw ticks and constructs 1-minute OHLCV candles in memory. Publishes completed candles to Redis for scanner consumption.

**In-memory state per symbol:**
```
{
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "current_candle": {
        "timestamp": "2026-04-04 09:15:00",   # candle open time
        "open": 2540.00,                        # first tick's LTP
        "high": 2545.50,                        # max LTP seen
        "low": 2538.20,                         # min LTP seen
        "close": 2543.50,                       # latest tick's LTP
        "volume": 150000                        # latest cumulative volume
    },
    "prev_volume": 0,                           # volume at candle start (for delta calc)
    "history": deque(maxlen=200)                 # rolling window of completed candles
}
```

**Candle construction logic:**

On every tick:
1. Look up symbol's candle state
2. Determine the 1-minute bucket: `candle_time = timestamp floored to minute`
3. If `candle_time == current_candle.timestamp` → **update existing candle:**
   - `high = max(high, ltp)`
   - `low = min(low, ltp)`
   - `close = ltp`
   - `volume = tick_volume - prev_volume` (delta from session start)
4. If `candle_time > current_candle.timestamp` → **new candle:**
   - Push `current_candle` to `history` deque
   - Publish completed candle to Redis Stream `candles:1m`
   - Start new candle: `open = high = low = close = ltp`

**Volume handling:**
- Broker WebSocket typically sends cumulative session volume, not per-candle volume
- Track `prev_volume` at each candle boundary
- Candle volume = `current_cumulative_volume - prev_volume`
- Reset `prev_volume` at each new candle close

**Minute boundary detection:**
- Use a 1-second timer that checks if any symbols have crossed a minute boundary
- Do NOT rely on tick arrival to trigger candle close — a symbol with no ticks in a minute still needs its candle closed
- For symbols with no ticks in a minute: close the candle with `open = high = low = close = previous_close`, `volume = 0`

**Higher timeframe construction (optional):**
- Maintain separate state for 5m, 15m candles
- On every 1m candle close, check if it completes a higher timeframe bucket
- 5m candle closes when minute is :00, :05, :10, :15, :20, ...
- Publish to separate Redis Streams: `candles:5m`, `candles:15m`
- Scanners subscribe to the timeframe they need

**Redis Stream output:**
```
Stream: candles:1m
Entry: {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "timestamp": "2026-04-04 09:15:00",
    "open": "2540.00",
    "high": "2545.50",
    "low": "2538.20",
    "close": "2543.50",
    "volume": "150000"
}
```

---

### 3. Scanner Processes

**Purpose:** Each scanner is an independent Python process that consumes 1-minute candles from Redis, maintains its own indicator state per symbol, and emits alerts when scan conditions are met.

**Key design principles:**
- Each scanner has its own Redis consumer group — independent offset tracking
- Each scanner maintains its own indicator state in memory — no shared state
- A scanner crash does not affect other scanners
- On restart, a scanner replays missed candles from Redis and reconstructs state
- Adding a new scanner requires zero changes to existing scanners or the candle builder

**Scanner structure:**
```
class BaseScanner:
    name: str                              # "rsi_scanner"
    consumer_group: str                    # "scanner_rsi"
    stream: str                            # "candles:1m"
    symbol_state: dict[str, IndicatorState]  # per-symbol indicator state

    def on_candle(symbol, exchange, candle):
        """Called for every completed 1m candle. Update indicators, check conditions."""
        pass

    def check_condition(symbol, exchange, state) -> ScanResult | None:
        """Return alert if scan condition is met, None otherwise."""
        pass

    def on_alert(result: ScanResult):
        """Publish alert to Redis alerts stream."""
        pass
```

**Example scanner — RSI Overbought:**
```
Scanner: rsi_scanner
Consumer group: scanner_rsi
Reads: candles:1m

Per-symbol state:
    - gains: deque(maxlen=14)     # last 14 gain values
    - losses: deque(maxlen=14)    # last 14 loss values
    - prev_close: float
    - rsi: float

On each candle:
    1. Calculate gain/loss from prev_close
    2. Update rolling gains/losses
    3. Compute RSI using Wilder's smoothing
    4. If RSI > 70 → emit alert
    5. If RSI > 80 → emit strong alert
    6. Store prev_close for next candle
```

**Example scanner — EMA Crossover:**
```
Scanner: ema_crossover_scanner
Consumer group: scanner_ema
Reads: candles:1m (or candles:5m for 5-minute EMA)

Per-symbol state:
    - ema_fast: float (e.g., EMA 9)
    - ema_slow: float (e.g., EMA 21)
    - prev_ema_fast: float
    - prev_ema_slow: float

On each candle:
    1. Update EMA fast and slow with new close
    2. Check for crossover:
       - Bullish: prev_fast <= prev_slow AND current_fast > current_slow
       - Bearish: prev_fast >= prev_slow AND current_fast < current_slow
    3. If crossover detected → emit alert
    4. Store prev values
```

**Example scanner — Volume Spike:**
```
Scanner: volume_spike_scanner
Consumer group: scanner_volume
Reads: candles:1m

Per-symbol state:
    - volume_history: deque(maxlen=20)
    - avg_volume: float

On each candle:
    1. Append candle volume to history
    2. Compute 20-period average volume
    3. volume_ratio = current_volume / avg_volume
    4. If volume_ratio > 3.0 → emit alert (3x average volume)
```

**Alert output format:**
```
Stream: alerts
Entry: {
    "scanner": "rsi_scanner",
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "signal": "RSI_OVERBOUGHT",
    "value": "74.5",
    "candle_close": "2543.50",
    "candle_timestamp": "2026-04-04 10:32:00",
    "alert_timestamp": "2026-04-04 10:33:00",
    "severity": "normal"
}
```

---

### 4. Bootstrap from Historify

**Purpose:** Seed indicator state at startup so scanners produce valid signals from the first candle of the trading day. Without bootstrap, RSI(14) would be blind for the first 14 minutes.

**Data source:** Historify (DuckDB) via OpenAlgo REST API with `source="Db"`.

**Why 1-minute data (not daily):**
- 1-minute is the lowest granularity stored in Historify
- Any higher timeframe (5m, 15m, 1h, daily) can be derived from 1m candles
- Daily candles cannot be used to initialize intraday indicators
- Storing 1m data means zero warm-up time for any timeframe scanner

**Bootstrap sequence:**

```
1. Load symbol list (500 symbols)

2. For each symbol, fetch last N 1-minute candles from Historify:
   
   client.history(
       symbol="RELIANCE",
       exchange="NSE",
       interval="1m",
       start_date="2026-04-03",    # previous trading day
       end_date="2026-04-03",
       source="Db"
   )
   
   This returns ~375 candles (one full trading session).
   
3. Feed these candles into each scanner's indicator computation:
   
   For RSI(14): replay last 15 candles through the RSI calculation
   For EMA(21): replay last 22 candles through the EMA calculation
   For Volume(20): replay last 21 candles to build volume average
   
4. Scanner is now warm — ready to process live candles at 9:15 AM
```

**Performance:**
- 500 symbols x 1 DuckDB query each = ~500 queries
- DuckDB is local, no network — each query takes ~1-5 ms
- Total bootstrap time: **1-3 seconds** for all 500 symbols
- No broker API involved — zero rate limit concerns

**Lookback requirements by indicator:**
```
Indicator          Lookback Needed      1m Candles to Fetch
─────────────────────────────────────────────────────────
RSI(14)            15 candles           15
EMA(9)             10 candles           10
EMA(21)            22 candles           22
EMA(50)            51 candles           51
EMA(200)           201 candles          201
MACD(12,26,9)      35 candles           35
Bollinger(20)      21 candles           21
ATR(14)            15 candles           15
VWAP               Full session         375 (one full day)
Supertrend(10,3)   11 candles           11
Volume SMA(20)     21 candles           21
```

**For multi-day indicators on 1m timeframe (e.g., EMA 200 on 1m):**
- 200 candles = less than one trading session (375 min/day)
- Fetch 1 day of 1m data — sufficient for most indicators
- For extreme lookbacks, fetch 2-3 days

**For higher timeframe scanners (e.g., RSI 14 on 5m):**
- Need 15 five-minute candles = 75 one-minute candles
- Fetch 75 one-minute candles from Historify
- Resample to 5m in memory (group by 5-minute buckets)
- Feed resampled candles into RSI calculation

---

### 5. End-of-Day Persistence

**Purpose:** Write all 1-minute candles built during the trading day back to Historify. This ensures tomorrow's bootstrap has today's data.

**When:** After market close (15:30 IST) + buffer (15:35 IST to ensure all ticks are processed).

**What to store:** Every completed 1-minute candle for every symbol from the current session.

**Storage math:**
```
500 symbols x 375 candles/day x ~100 bytes = ~18.75 MB/day
One month (22 trading days) = ~412 MB
One year = ~4.5 GB
DuckDB compressed = ~1-1.5 GB/year
```

**Write strategy:**
- Batch insert all candles in one transaction per symbol
- Use OpenAlgo's Historify write API if available
- Alternatively, write directly to DuckDB file if the scanner runs on the same machine

**Validation before write:**
- Verify candle count per symbol (should be ~375 for a full session)
- Flag symbols with significantly fewer candles (possible data gaps)
- Do not overwrite existing data — append only, skip duplicates by timestamp

---

### 6. Results Aggregator

**Purpose:** Consumes all scanner alerts from the `alerts` Redis Stream and routes them to output destinations.

**Output destinations:**

**Dashboard WebSocket:**
- Run a lightweight WebSocket server (e.g., FastAPI + WebSocket)
- Frontend connects and receives live scan results
- Display as a sortable, filterable table of active signals

**Webhook notifications:**
- POST alert JSON to configured webhook URLs
- Use for Telegram bots, Discord bots, custom notification systems
- Include rate limiting to prevent alert spam (e.g., max 1 alert per symbol per 5 minutes)

**OpenAlgo Order API:**
- For automated execution based on scan results
- Route through OpenAlgo's PlaceSmartOrder API
- Requires additional risk checks before placing orders:
  - Maximum position size
  - Maximum number of open positions
  - Daily loss limit
  - Symbol-level cooldown after order

**Log storage:**
- Write all alerts to a local SQLite or CSV file
- Enables post-session analysis: "which scanners fired most often?", "what was the hit rate?"

---

## Redis Streams Configuration

### Stream Topology

```
ticks:raw           ← Tick receiver publishes all ticks
    │
    └── Consumer: candle_builder (group: builder)
            │
            ├── candles:1m    ← Completed 1-minute candles
            │   ├── Consumer group: scanner_rsi
            │   ├── Consumer group: scanner_ema
            │   ├── Consumer group: scanner_volume
            │   └── Consumer group: scanner_custom_N
            │
            ├── candles:5m    ← Completed 5-minute candles (optional)
            │   └── Consumer group: scanner_ema_5m
            │
            └── candles:15m   ← Completed 15-minute candles (optional)
                └── Consumer group: scanner_breakout_15m

alerts              ← All scanners publish alerts here
    └── Consumer: results_aggregator (group: aggregator)
```

### Retention Policy

```
ticks:raw      → MAXLEN ~100000    (~50 seconds of ticks at 2000/sec)
candles:1m     → MAXLEN ~50000     (~100 minutes of candles for 500 symbols)
candles:5m     → MAXLEN ~10000     (~100 minutes of 5m candles for 500 symbols)
alerts         → MAXLEN ~10000     (last ~10000 alerts)
```

Set MAXLEN to prevent Redis memory from growing unbounded. These values provide enough buffer for any consumer to catch up after a brief restart.

### Consumer Group Setup

Create consumer groups on first run:
```
XGROUP CREATE ticks:raw builder $ MKSTREAM
XGROUP CREATE candles:1m scanner_rsi $ MKSTREAM
XGROUP CREATE candles:1m scanner_ema $ MKSTREAM
XGROUP CREATE candles:1m scanner_volume $ MKSTREAM
XGROUP CREATE alerts aggregator $ MKSTREAM
```

Use `$` as the start ID so consumers only read new messages. For bootstrap replay, use `0` to read from the beginning of the stream.

---

## Process Management

### Recommended Process Layout

```
Process 1: tick_receiver         — Single async process
Process 2: candle_builder        — Single process
Process 3: scanner_rsi           — Independent scanner
Process 4: scanner_ema           — Independent scanner
Process 5: scanner_volume        — Independent scanner
Process 6: results_aggregator    — Single process
```

Total: 6 lightweight Python processes. Each uses ~20-50 MB RAM.

### Startup Order

```
1. Redis server (must be running first)
2. OpenAlgo application (WebSocket proxy must be available)
3. tick_receiver (connects to OpenAlgo WebSocket, starts publishing ticks)
4. candle_builder (starts consuming ticks, building candles)
5. scanners (bootstrap from Historify, then consume candles)
6. results_aggregator (starts consuming alerts)
```

### Process Supervision

Use any process manager to keep services running:
- **systemd** (Linux production)
- **supervisord** (cross-platform, Python-native)
- **PM2** (if Node.js is already in the stack)
- **Simple bash script** (development)

Each process should:
- Log to its own file: `logs/tick_receiver.log`, `logs/scanner_rsi.log`, etc.
- Handle SIGTERM gracefully — flush state, acknowledge pending Redis messages
- Auto-restart on crash with exponential backoff

### Health Monitoring

Each process publishes a heartbeat to Redis every 10 seconds:
```
Key: health:{process_name}
Value: {"status": "running", "last_tick": "...", "symbols": 500, "uptime": 3600}
TTL: 30 seconds (auto-expires if process dies)
```

The results aggregator (or a separate monitor) checks these keys and alerts if any process goes silent.

---

## Configuration

### Main Config File: `scanner_config.yaml`

```yaml
# OpenAlgo connection
openalgo:
  host: "http://127.0.0.1:5000"
  websocket: "ws://127.0.0.1:8765"
  api_key: "your_api_key_here"

# Redis connection
redis:
  host: "127.0.0.1"
  port: 6379
  db: 0

# Symbol universe
symbols:
  file: "symbols.json"                    # symbol list file
  mode: "LTP"                             # LTP, Quote, or Depth
  subscribe_batch_size: 50                # symbols per subscribe message

# Candle builder
candle_builder:
  timeframes: ["1m", "5m"]                # timeframes to build
  history_length: 200                     # candles to keep in memory per symbol

# Bootstrap
bootstrap:
  source: "Db"                            # Historify
  lookback_days: 1                        # days of 1m data to fetch
  exchange: "NSE"                         # default exchange

# End-of-day persistence
eod:
  enabled: true
  write_time: "15:35"                     # IST
  target: "historify"                     # where to write candles

# Alerts
alerts:
  webhook_urls: []                        # list of webhook endpoints
  rate_limit_seconds: 300                 # min seconds between alerts for same symbol+scanner
  max_alerts_per_minute: 50               # global rate limit
```

### Symbol List File: `symbols.json`

```json
{
  "symbols": [
    {"symbol": "RELIANCE", "exchange": "NSE"},
    {"symbol": "ICICIBANK", "exchange": "NSE"},
    {"symbol": "HDFCBANK", "exchange": "NSE"},
    {"symbol": "TCS", "exchange": "NSE"},
    {"symbol": "INFY", "exchange": "NSE"}
  ]
}
```

### Scanner Definition File: `scanners.yaml`

```yaml
scanners:
  - name: "rsi_overbought"
    enabled: true
    timeframe: "1m"
    indicator: "RSI"
    params:
      period: 14
    condition: "RSI > 70"
    severity: "normal"

  - name: "rsi_oversold"
    enabled: true
    timeframe: "1m"
    indicator: "RSI"
    params:
      period: 14
    condition: "RSI < 30"
    severity: "normal"

  - name: "ema_bullish_cross"
    enabled: true
    timeframe: "5m"
    indicator: "EMA_CROSS"
    params:
      fast_period: 9
      slow_period: 21
    condition: "CROSS_ABOVE"
    severity: "high"

  - name: "volume_spike"
    enabled: true
    timeframe: "1m"
    indicator: "VOLUME_RATIO"
    params:
      period: 20
      threshold: 3.0
    condition: "RATIO > 3.0"
    severity: "high"
```

---

## Data Flow Timing

### Typical Trading Day Timeline

```
08:45  Scanner service starts
       └── Redis health check
       └── OpenAlgo connectivity check

08:50  Bootstrap phase
       └── Fetch 1m candle history from Historify for all 500 symbols
       └── Initialize indicator state for all scanners
       └── Total time: 1-3 seconds

08:55  Tick receiver connects to OpenAlgo WebSocket
       └── Authenticate
       └── Subscribe to 500 symbols in batches
       └── Ready to receive ticks

09:15  Market opens — ticks start flowing
       └── Candle builder starts constructing 1m candles
       └── First candle closes at 09:16:00

09:16  First candle close
       └── Scanners receive first live candle
       └── Combined with bootstrap history, indicators are fully warm
       └── First scan results emitted (if conditions met)

09:16 - 15:29  Continuous operation
       └── ~500-2000 ticks/second
       └── ~500 candle events per minute (one per symbol)
       └── Scanners evaluate conditions on every candle close
       └── Alerts emitted in real-time

15:30  Market close
       └── Final candles closed
       └── Final scan results emitted

15:35  End-of-day persistence
       └── Write all 1m candles to Historify
       └── Verify candle counts
       └── Log session summary

15:40  Service enters idle mode (or shuts down)
       └── Optional: keep running for after-hours analysis
```

### Latency Budget

```
Broker WebSocket → tick arrives           ~50-200 ms (broker dependent)
Tick → Redis Stream (ticks:raw)           ~1 ms
Redis → Candle builder processes tick     ~1 ms
Candle close → Redis Stream (candles:1m)  ~1 ms
Redis → Scanner processes candle          ~1 ms
Scanner → indicator compute               ~0.01 ms (in-memory math)
Alert → Redis Stream (alerts)             ~1 ms
Alert → webhook/UI delivery               ~10-50 ms
─────────────────────────────────────────────────────
Total: tick to alert                      ~65-260 ms
```

The bottleneck is broker WebSocket latency, not the scanner pipeline.

---

## Error Handling

### Tick Receiver Disconnection

```
If WebSocket disconnects:
    1. Log disconnect reason
    2. Wait 1 second
    3. Reconnect to OpenAlgo WebSocket
    4. Re-authenticate
    5. Re-subscribe to all symbols
    6. Resume publishing ticks to Redis

Candle builder handles the gap:
    - Missing ticks during disconnect = candle may have incorrect H/L/V
    - Close the candle normally at minute boundary
    - Flag the candle as "partial" in metadata
    - Scanners should handle partial candles gracefully
```

### Scanner Process Crash

```
If a scanner crashes and restarts:
    1. Reconnect to Redis
    2. Read pending messages from consumer group (messages delivered but not ACK'd)
    3. If gap is small (< 5 minutes): replay missed candles from Redis Stream
    4. If gap is large (> 5 minutes): re-bootstrap from Historify
    5. Resume normal processing
```

### Redis Unavailability

```
If Redis goes down:
    - Tick receiver: buffer ticks in memory (bounded queue, drop oldest)
    - Candle builder: continue building candles in memory, retry Redis publish
    - Scanners: pause, retry connection with backoff
    - When Redis returns: resume from last ACK'd offset
```

### Market Data Gaps

```
If a symbol stops receiving ticks for > 2 minutes during market hours:
    1. Log warning: "No ticks for SYMBOL in 2 minutes"
    2. Continue closing empty candles (close = last known close, volume = 0)
    3. Do NOT emit scanner alerts on stale data — mark symbol as "stale"
    4. Resume normal processing when ticks return
```

---

## Scaling Path

### Current Design: Single Machine (500 Symbols)

```
Processes: 6 (tick receiver + candle builder + 3 scanners + aggregator)
Memory: ~200 MB total
CPU: < 10% of a modern machine
Redis: Single instance, < 100 MB memory
```

### Scale to 2000 Symbols

```
Same architecture, just more symbols:
- OpenAlgo WebSocket supports 3000 symbols (connection pooling)
- Candle builder memory: 2000 x 200 candles x 100 bytes = ~40 MB
- Scanner memory: ~40 MB per scanner
- Redis throughput: ~8000 ticks/second — well within limits
- No architectural changes needed
```

### Scale to 5000+ Symbols (When to Introduce Kafka)

```
Replace Redis Streams with Kafka:
- Partition ticks by symbol hash → distribute candle building across N workers
- Each candle builder handles a subset of symbols
- Scanners consume from Kafka with consumer groups (same pattern as Redis)
- Kafka handles cross-machine distribution automatically

Add QuestDB:
- Replace DuckDB for candle storage
- Real-time ingestion via ILP (InfluxDB Line Protocol)
- Sub-millisecond queries for bootstrap and analytics
- Grafana dashboards for scanner monitoring
```

---

## Directory Structure

```
scanner-service/
├── config/
│   ├── scanner_config.yaml          # Main configuration
│   ├── scanners.yaml                # Scanner definitions
│   └── symbols.json                 # Symbol universe
│
├── core/
│   ├── tick_receiver.py             # WebSocket → Redis tick publisher
│   ├── candle_builder.py            # Tick consumer → candle constructor
│   └── results_aggregator.py        # Alert consumer → output routing
│
├── scanners/
│   ├── base_scanner.py              # Abstract scanner class
│   ├── rsi_scanner.py               # RSI overbought/oversold
│   ├── ema_scanner.py               # EMA crossover
│   ├── volume_scanner.py            # Volume spike detection
│   └── custom_scanner.py            # Template for custom scanners
│
├── indicators/
│   ├── rsi.py                       # RSI calculation (Wilder's smoothing)
│   ├── ema.py                       # EMA calculation
│   ├── sma.py                       # SMA calculation
│   ├── atr.py                       # ATR calculation
│   ├── vwap.py                      # VWAP calculation
│   └── supertrend.py                # Supertrend calculation
│
├── bootstrap/
│   ├── historify_loader.py          # Fetch 1m candles from Historify
│   └── indicator_seeder.py          # Seed indicator state from history
│
├── persistence/
│   └── eod_writer.py                # End-of-day candle persistence
│
├── utils/
│   ├── redis_client.py              # Redis connection and stream helpers
│   ├── openalgo_client.py           # OpenAlgo API wrapper
│   ├── timeframe.py                 # Candle time bucket utilities
│   └── logger.py                    # Structured logging
│
├── logs/                            # Process log files
├── requirements.txt
├── run_all.sh                       # Start all processes
└── README.md
```

---

## Dependencies

```
# requirements.txt
openalgo                    # OpenAlgo SDK — API and WebSocket
redis>=5.0                  # Redis Streams support
websockets>=12.0            # Async WebSocket client
pyyaml                      # Configuration parsing
numpy                       # Indicator math
pandas                      # Data manipulation (bootstrap only)
```

No Kafka, no QuestDB, no heavy dependencies. Six lightweight Python processes and a Redis server.

---

## Key Design Decisions Summary

| Decision | Choice | Rationale |
|---|---|---|
| Data source for real-time | WebSocket ticks (not REST API) | Zero rate limits, true real-time |
| Message bus | Redis Streams | Consumer groups + persistence + minimal ops for single-machine |
| Candle storage granularity | 1-minute only | Any timeframe derivable from 1m; daily cannot produce intraday |
| Bootstrap source | Historify (DuckDB) 1m candles | Local, instant, zero rate limits, zero warm-up |
| Indicator computation | In-memory per scanner | Microsecond latency, ~10 MB memory per scanner |
| Process model | Separate processes per component | Fault isolation, independent restart, no shared state |
| Higher timeframes | Derived from 1m in candle builder | Single source of truth, no redundant storage |
| Scanner independence | Separate Redis consumer groups | Add/remove/crash scanners without affecting others |
| End-of-day persistence | Write 1m candles back to Historify | Seeds next day's bootstrap, ~18 MB/day |
| When to upgrade to Kafka | 5000+ symbols or multi-machine | Overkill below that threshold |
