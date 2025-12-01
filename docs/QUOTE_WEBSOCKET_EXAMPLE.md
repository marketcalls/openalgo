# WebSocket Quote Feed Examples

This guide provides comprehensive examples for using the OpenAlgo WebSocket Quote Feed to receive real-time market data. The Quote feed provides OHLC (Open, High, Low, Close) data along with LTP, bid/ask prices, and volume information.

## Prerequisites

1. **Install OpenAlgo Python SDK**:
   ```bash
   pip install openalgo
   ```

2. **Ensure OpenAlgo server is running**:
   - REST API server (default: `http://127.0.0.1:5000`)
   - WebSocket proxy server (default: `ws://127.0.0.1:8765`)

3. **Get your API key** from the OpenAlgo dashboard after logging in.

## Basic Example

This is the simplest way to subscribe to quote data for multiple instruments:

```python
from openalgo import api
import time

# Initialize the API client
client = api(
    api_key="your_api_key_here",          # Replace with your API key
    host="http://127.0.0.1:5000",          # REST API host
    ws_url="ws://127.0.0.1:8765"           # WebSocket URL
)

# Define instruments to subscribe
instruments_list = [
    {"exchange": "NSE_INDEX", "symbol": "NIFTY"},
    {"exchange": "NSE", "symbol": "INFY"},
    {"exchange": "NSE", "symbol": "TCS"}
]

# Callback function for real-time updates
def on_data_received(data):
    print("Quote Update:")
    print(data)

# Connect and subscribe
client.connect()
client.subscribe_quote(instruments_list, on_data_received=on_data_received)

# Receive data for 100 iterations
for i in range(100):
    print(f"\nPoll {i+1}:")
    print(client.get_quotes())
    time.sleep(0.5)

# Cleanup
client.unsubscribe_quote(instruments_list)
client.disconnect()
```

## Client Initialization Parameters

The `api` class accepts three parameters for WebSocket connectivity:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `api_key` | Your OpenAlgo API key | Required |
| `host` | REST API server URL | `http://127.0.0.1:5000` |
| `ws_url` | WebSocket proxy URL | `ws://127.0.0.1:8765` |

### Local Setup Example

```python
client = api(
    api_key="your_api_key_here",
    host="http://127.0.0.1:5000",
    ws_url="ws://127.0.0.1:8765"
)
```

### Remote Server / ngrok Example

```python
client = api(
    api_key="your_api_key_here",
    host="https://your-domain.ngrok.io",
    ws_url="wss://your-domain.ngrok.io/ws"
)
```

### Separate WebSocket Server Example

If your WebSocket server runs on a different host:

```python
client = api(
    api_key="your_api_key_here",
    host="http://192.168.1.100:5000",      # REST API on one server
    ws_url="ws://192.168.1.101:8765"       # WebSocket on another server
)
```

## Quote Data Format

### Callback Data (on_data_received)

When you receive quote data via callback, it has this structure:

```python
{
    "type": "market_data",
    "symbol": "INFY",
    "exchange": "NSE",
    "mode": 2,                    # Mode 2 = Quote
    "data": {
        "open": 1532.1,           # Day's Open
        "high": 1543.8,           # Day's High
        "low": 1532.1,            # Day's Low
        "close": 1536.8,          # Previous Close
        "ltp": 1536.8,            # Last Traded Price
        "volume": 907035,         # Traded Volume
        "timestamp": 1764095400000  # Unix timestamp in milliseconds
    }
}
```

### Polling Data (get_quotes())

When you poll using `client.get_quotes()`, data is nested by exchange and symbol:

```python
{
    "quote": {
        "NSE_INDEX": {
            "NIFTY": {
                "timestamp": 1764095400000,
                "open": 25842.95,
                "high": 26035.0,
                "low": 25842.95,
                "close": 26035.0,
                "ltp": 26035.0,
                "volume": 0
            }
        },
        "NSE": {
            "INFY": {
                "timestamp": 1764095400000,
                "open": 1532.1,
                "high": 1543.8,
                "low": 1532.1,
                "close": 1536.8,
                "ltp": 1536.8,
                "volume": 907035
            },
            "TCS": {
                "timestamp": 1764095400000,
                "open": 3118.8,
                "high": 3139.0,
                "low": 3117.0,
                "close": 3130.7,
                "ltp": 3130.7,
                "volume": 292559
            }
        }
    }
}
```

## Callback vs Polling

### Method 1: Callback-Based (Real-time)

The callback function is invoked automatically whenever new data arrives:

```python
def on_data_received(data):
    symbol = data.get("symbol")
    exchange = data.get("exchange")
    quote = data.get("data", {})

    ltp = quote.get("ltp", 0)
    close = quote.get("close", ltp)
    change = ltp - close

    print(f"[{exchange}] {symbol}: LTP={ltp}, Change={change:+.2f}")

client.connect()
client.subscribe_quote(instruments_list, on_data_received=on_data_received)

# Keep running to receive callbacks
time.sleep(60)
```

### Method 2: Polling (On-Demand)

Use `get_quotes()` to fetch the latest cached quote data:

```python
client.connect()
client.subscribe_quote(instruments_list, on_data_received=lambda x: None)

# Poll every second
while True:
    result = client.get_quotes()
    quotes = result.get("quote", {})

    # Iterate through exchanges and symbols
    for exchange, symbols in quotes.items():
        for symbol, data in symbols.items():
            print(f"[{exchange}] {symbol}: {data.get('ltp')}")
    time.sleep(1)
```

### Method 3: Combined (Recommended)

Use callbacks for real-time processing and polling for periodic checks:

```python
from collections import defaultdict

# Track tick counts
tick_counts = defaultdict(int)

def on_data_received(data):
    symbol = data.get("symbol")
    tick_counts[symbol] += 1

client.connect()
client.subscribe_quote(instruments_list, on_data_received=on_data_received)

# Report statistics every 5 seconds
for _ in range(12):
    time.sleep(5)
    result = client.get_quotes()
    quotes = result.get("quote", {})

    print("\n--- 5 Second Report ---")
    for exchange, symbols in quotes.items():
        for symbol, quote_data in symbols.items():
            print(f"[{exchange}] {symbol}: LTP={quote_data.get('ltp')}, Ticks={tick_counts[symbol]}")
```

## Advanced Examples

### Example 1: Price Alert System

```python
from openalgo import api
import time

client = api(
    api_key="your_api_key_here",
    host="http://127.0.0.1:5000",
    ws_url="ws://127.0.0.1:8765"
)

# Price alert configuration
alerts = {
    "NIFTY": {"above": 24500, "below": 24000},
    "INFY": {"above": 1500, "below": 1400},
    "TCS": {"above": 4200, "below": 4000}
}

triggered_alerts = set()

def check_alerts(data):
    symbol = data.get("symbol")
    quote = data.get("data", {})
    ltp = quote.get("ltp", 0)

    if symbol not in alerts:
        return

    alert_config = alerts[symbol]
    alert_key_above = f"{symbol}_above"
    alert_key_below = f"{symbol}_below"

    if ltp >= alert_config["above"] and alert_key_above not in triggered_alerts:
        print(f"ALERT: {symbol} crossed above {alert_config['above']}! Current: {ltp}")
        triggered_alerts.add(alert_key_above)

    if ltp <= alert_config["below"] and alert_key_below not in triggered_alerts:
        print(f"ALERT: {symbol} fell below {alert_config['below']}! Current: {ltp}")
        triggered_alerts.add(alert_key_below)

instruments_list = [
    {"exchange": "NSE_INDEX", "symbol": "NIFTY"},
    {"exchange": "NSE", "symbol": "INFY"},
    {"exchange": "NSE", "symbol": "TCS"}
]

client.connect()
client.subscribe_quote(instruments_list, on_data_received=check_alerts)

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    client.unsubscribe_quote(instruments_list)
    client.disconnect()
    print("Disconnected.")
```

### Example 2: Track Consecutive Ticks Above Level

```python
from openalgo import api
import time
from collections import defaultdict

client = api(
    api_key="your_api_key_here",
    host="http://127.0.0.1:5000",
    ws_url="ws://127.0.0.1:8765"
)

# Configuration
PRICE_LEVEL = 24500
CONSECUTIVE_THRESHOLD = 5

# Tracking
consecutive_above = defaultdict(int)
signal_triggered = set()

def track_consecutive(data):
    symbol = data.get("symbol")
    quote = data.get("data", {})
    ltp = quote.get("ltp", 0)

    if ltp > PRICE_LEVEL:
        consecutive_above[symbol] += 1

        # Check if this is the 6th tick after 5 consecutive ticks above level
        if consecutive_above[symbol] == CONSECUTIVE_THRESHOLD + 1:
            if symbol not in signal_triggered:
                print(f"SIGNAL: {symbol} - 6th tick after {CONSECUTIVE_THRESHOLD} consecutive above {PRICE_LEVEL}")
                print(f"  Current LTP: {ltp}")
                signal_triggered.add(symbol)
    else:
        # Reset counter when price falls below level
        consecutive_above[symbol] = 0
        signal_triggered.discard(symbol)

instruments_list = [
    {"exchange": "NSE_INDEX", "symbol": "NIFTY"}
]

client.connect()
client.subscribe_quote(instruments_list, on_data_received=track_consecutive)

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    client.unsubscribe_quote(instruments_list)
    client.disconnect()
```

### Example 3: OHLC Range Tracker

```python
from openalgo import api
import time

client = api(
    api_key="your_api_key_here",
    host="http://127.0.0.1:5000",
    ws_url="ws://127.0.0.1:8765"
)

def display_ohlc_range(data):
    symbol = data.get("symbol")
    quote = data.get("data", {})

    open_price = quote.get("open", 0)
    high = quote.get("high", 0)
    low = quote.get("low", 0)
    ltp = quote.get("ltp", 0)

    if high > 0 and low > 0:
        day_range = high - low
        range_pct = (day_range / low) * 100 if low > 0 else 0
        position = ((ltp - low) / day_range) * 100 if day_range > 0 else 50

        print(f"{symbol}: Range={day_range:.2f} ({range_pct:.2f}%), Position={position:.1f}%")

instruments_list = [
    {"exchange": "NSE_INDEX", "symbol": "NIFTY"},
    {"exchange": "NSE", "symbol": "RELIANCE"},
    {"exchange": "NSE", "symbol": "TCS"}
]

client.connect()
client.subscribe_quote(instruments_list, on_data_received=display_ohlc_range)

try:
    time.sleep(30)
finally:
    client.unsubscribe_quote(instruments_list)
    client.disconnect()
```

### Example 4: Multi-Exchange Subscription

```python
from openalgo import api
import time

client = api(
    api_key="your_api_key_here",
    host="http://127.0.0.1:5000",
    ws_url="ws://127.0.0.1:8765"
)

# Subscribe to different exchanges
instruments_list = [
    # Index
    {"exchange": "NSE_INDEX", "symbol": "NIFTY"},
    {"exchange": "NSE_INDEX", "symbol": "BANKNIFTY"},

    # NSE Cash
    {"exchange": "NSE", "symbol": "RELIANCE"},
    {"exchange": "NSE", "symbol": "TCS"},

    # BSE Cash
    {"exchange": "BSE", "symbol": "RELIANCE"},

    # NFO (Futures)
    {"exchange": "NFO", "symbol": "NIFTY28NOV25FUT"},

    # MCX Commodities
    {"exchange": "MCX", "symbol": "GOLDPETAL28NOV25FUT"}
]

def on_data_received(data):
    exchange = data.get("exchange")
    symbol = data.get("symbol")
    quote = data.get("data", {})
    ltp = quote.get("ltp", 0)
    print(f"[{exchange}] {symbol}: {ltp}")

client.connect()
client.subscribe_quote(instruments_list, on_data_received=on_data_received)

try:
    time.sleep(60)
finally:
    client.unsubscribe_quote(instruments_list)
    client.disconnect()
```

## FAQ: WebSocket Performance and Tick Detection

### Q: How do we know WebSocket data is not overloading the PC?

**A: OpenAlgo has built-in optimizations, but you should also monitor your client-side performance.**

**Built-in OpenAlgo Features:**

1. **O(1) Subscription Index** - Server-side lookup is constant time regardless of how many symbols you subscribe to (reduces CPU 60-70%)

2. **Message Throttling** - LTP updates are throttled to max 20 messages/second per symbol to prevent flooding

3. **Batch Sending** - Multiple updates are batched together for efficient delivery

**What OpenAlgo Does NOT Track (You Must Implement):**

- Client-side tick counting
- Consecutive tick detection
- Custom signal generation

### Q: Are there built-in features for detecting tick signals?

**A: No. Tick counting and signal detection must be implemented in your callback.**

OpenAlgo provides the raw data stream. Your callback function is responsible for:
- Counting ticks
- Tracking consecutive conditions
- Generating trading signals

### Q: How do I handle 700 stocks and detect "5 consecutive ticks above level, execute on 6th"?

**A: Here's a complete example with verification that the algo executed on exactly the 6th tick:**

```python
from openalgo import api
import time
from collections import defaultdict
from datetime import datetime

client = api(
    api_key="your_api_key_here",
    host="http://127.0.0.1:5000",
    ws_url="ws://127.0.0.1:8765"
)

# Configuration for each stock
# Format: {"SYMBOL": {"level": price_level, "action": "BUY" or "SELL"}}
stock_levels = {
    "RELIANCE": {"level": 2900, "action": "BUY"},
    "TCS": {"level": 4200, "action": "SELL"},
    "INFY": {"level": 1500, "action": "BUY"},
    # ... add up to 700 stocks
}

# Tracking state per symbol
consecutive_above = defaultdict(int)  # Count of consecutive ticks above level
signal_executed = set()               # Track which symbols have triggered
tick_history = defaultdict(list)      # Store tick details for verification

CONSECUTIVE_THRESHOLD = 5  # Must stay above for 5 ticks

def on_tick(data):
    symbol = data.get("symbol")
    quote = data.get("data", {})
    ltp = quote.get("ltp", 0)
    timestamp = datetime.now().isoformat()

    # Skip if not in our watch list
    if symbol not in stock_levels:
        return

    config = stock_levels[symbol]
    level = config["level"]
    action = config["action"]

    # Record tick for audit trail
    tick_info = {
        "tick_num": consecutive_above[symbol] + 1 if ltp > level else 0,
        "ltp": ltp,
        "level": level,
        "above": ltp > level,
        "timestamp": timestamp
    }

    if ltp > level:
        consecutive_above[symbol] += 1
        tick_history[symbol].append(tick_info)

        current_count = consecutive_above[symbol]

        # Execute on 6th tick (after 5 consecutive above)
        if current_count == CONSECUTIVE_THRESHOLD + 1:
            if symbol not in signal_executed:
                # VERIFICATION: Log exactly which tick triggered
                print(f"\n{'='*60}")
                print(f"SIGNAL TRIGGERED: {symbol}")
                print(f"Action: {action}")
                print(f"Trigger Price: {ltp}")
                print(f"Level: {level}")
                print(f"This is tick #{current_count} (6th tick after 5 consecutive)")
                print(f"Timestamp: {timestamp}")
                print(f"\nTick History (last 6 ticks):")
                for i, t in enumerate(tick_history[symbol][-6:], 1):
                    marker = " <-- EXECUTED" if i == 6 else ""
                    print(f"  Tick {t['tick_num']}: LTP={t['ltp']} at {t['timestamp']}{marker}")
                print(f"{'='*60}\n")

                # Execute the trade
                execute_trade(symbol, action, ltp)
                signal_executed.add(symbol)
    else:
        # Reset counter when price falls below level
        if consecutive_above[symbol] > 0:
            print(f"{symbol}: Reset at tick {consecutive_above[symbol]} (LTP {ltp} fell below {level})")
        consecutive_above[symbol] = 0
        tick_history[symbol].clear()
        signal_executed.discard(symbol)  # Allow re-trigger if price crosses again

def execute_trade(symbol, action, price):
    """Execute the trading logic"""
    print(f"EXECUTING: {action} {symbol} at {price}")
    # Uncomment to place actual order:
    # response = client.placeorder(
    #     strategy="ConsecutiveTick",
    #     symbol=symbol,
    #     action=action,
    #     exchange="NSE",
    #     price_type="MARKET",
    #     product="MIS",
    #     quantity=1
    # )
    # print(f"Order response: {response}")

# Build instruments list from stock_levels
instruments_list = [
    {"exchange": "NSE", "symbol": symbol}
    for symbol in stock_levels.keys()
]

print(f"Subscribing to {len(instruments_list)} stocks...")
client.connect()
client.subscribe_quote(instruments_list, on_data_received=on_tick)

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    client.unsubscribe_quote(instruments_list)
    client.disconnect()
```

**Sample Output Showing 6th Tick Execution:**

```
============================================================
SIGNAL TRIGGERED: RELIANCE
Action: BUY
Trigger Price: 2915.50
Level: 2900
This is tick #6 (6th tick after 5 consecutive)
Timestamp: 2025-11-26T10:30:15.123456

Tick History (last 6 ticks):
  Tick 1: LTP=2901.00 at 2025-11-26T10:30:10.100
  Tick 2: LTP=2905.25 at 2025-11-26T10:30:11.200
  Tick 3: LTP=2908.50 at 2025-11-26T10:30:12.300
  Tick 4: LTP=2910.00 at 2025-11-26T10:30:13.400
  Tick 5: LTP=2912.75 at 2025-11-26T10:30:14.500
  Tick 6: LTP=2915.50 at 2025-11-26T10:30:15.123 <-- EXECUTED
============================================================

EXECUTING: BUY RELIANCE at 2915.50
```

### Q: How do I verify the system isn't lagging behind with 700 stocks?

**A: Add performance monitoring to your callback:**

```python
from collections import deque
import time

# Performance tracking
tick_times = deque(maxlen=1000)
processing_times = deque(maxlen=1000)
lag_warnings = 0

def on_tick_with_monitoring(data):
    global lag_warnings
    receive_time = time.perf_counter()

    # Track inter-tick timing
    if tick_times:
        inter_tick_ms = (receive_time - tick_times[-1]) * 1000
        if inter_tick_ms > 100:  # Gap > 100ms might indicate lag
            lag_warnings += 1
            print(f"LAG WARNING #{lag_warnings}: {inter_tick_ms:.0f}ms gap between ticks")

    tick_times.append(receive_time)

    # Process the tick (your logic here)
    process_start = time.perf_counter()
    # ... your consecutive tick logic ...
    process_end = time.perf_counter()

    processing_ms = (process_end - process_start) * 1000
    processing_times.append(processing_ms)

    # Warn if processing is slow
    if processing_ms > 5:
        print(f"SLOW: {data.get('symbol')} took {processing_ms:.1f}ms to process")

# Print stats periodically
def print_performance_stats():
    if processing_times:
        avg_processing = sum(processing_times) / len(processing_times)
        max_processing = max(processing_times)
        ticks_per_sec = len(tick_times) / (tick_times[-1] - tick_times[0]) if len(tick_times) > 1 else 0

        print(f"\n--- Performance Report ---")
        print(f"Ticks/sec: {ticks_per_sec:.0f}")
        print(f"Avg processing: {avg_processing:.2f}ms")
        print(f"Max processing: {max_processing:.2f}ms")
        print(f"Lag warnings: {lag_warnings}")

        # Health check
        if avg_processing < 1 and lag_warnings < 10:
            print("STATUS: HEALTHY - System keeping up with data")
        elif avg_processing < 5:
            print("STATUS: OK - Minor delays but acceptable")
        else:
            print("STATUS: WARNING - Processing too slow, consider optimization")
```

### Performance Guidelines for 700 Stocks

| Metric | Healthy | Warning | Critical |
|--------|---------|---------|----------|
| Ticks/sec | < 5000 | 5000-10000 | > 10000 |
| Avg Processing | < 1ms | 1-5ms | > 5ms |
| Inter-tick Gap | < 50ms | 50-100ms | > 100ms |
| Lag Warnings/min | < 5 | 5-20 | > 20 |

**Key Points:**
- OpenAlgo handles the server-side optimization (throttling, batching)
- You must implement tick counting and signal detection in your callback
- Use `tick_history` to verify exactly which tick triggered your signal
- Monitor processing time to ensure your callback doesn't become a bottleneck

## Detecting WebSocket Overload

Monitor these metrics to detect if WebSocket data is overwhelming your system.

### Monitor Update Rate

Track how many ticks per second you're receiving to detect connection issues or overload:

```python
from openalgo import api
import time

client = api(
    api_key="your_api_key_here",
    host="http://127.0.0.1:5000",
    ws_url="ws://127.0.0.1:8765"
)

update_count = 0
start_time = time.time()

def on_tick(data):
    global update_count
    update_count += 1

    # Print rate every 10 seconds
    elapsed = time.time() - start_time
    if int(elapsed) % 10 == 0 and int(elapsed) > 0:
        rate = update_count / elapsed
        print(f"Update rate: {rate:.1f}/sec")

        # Warning thresholds
        if rate < 100:
            print("LOW: Possible connection issue")
        elif rate > 5000:
            print("HIGH: May need throttling")

instruments_list = [
    {"exchange": "NSE_INDEX", "symbol": "NIFTY"},
    {"exchange": "NSE", "symbol": "RELIANCE"}
]

client.connect()
client.subscribe_quote(instruments_list, on_data_received=on_tick)

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    client.unsubscribe_quote(instruments_list)
    client.disconnect()
```

### Monitor Tick Latency

Measure the delay between when the broker sends data and when you receive it:

```python
from openalgo import api
import time

client = api(
    api_key="your_api_key_here",
    host="http://127.0.0.1:5000",
    ws_url="ws://127.0.0.1:8765"
)

def on_tick(data):
    receive_time = time.time() * 1000  # Convert to milliseconds
    symbol = data.get("symbol")
    quote = data.get("data", {})

    # Timestamp is in milliseconds from broker
    broker_time = quote.get("timestamp", 0)

    if broker_time > 0:
        latency_ms = receive_time - broker_time

        if latency_ms > 100:
            print(f"High latency: {latency_ms:.0f}ms for {symbol}")

instruments_list = [
    {"exchange": "NSE_INDEX", "symbol": "NIFTY"}
]

client.connect()
client.subscribe_quote(instruments_list, on_data_received=on_tick)

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    client.unsubscribe_quote(instruments_list)
    client.disconnect()
```

### Monitor Processing Time

Ensure your callback function completes quickly to avoid blocking:

```python
from openalgo import api
import time

client = api(
    api_key="your_api_key_here",
    host="http://127.0.0.1:5000",
    ws_url="ws://127.0.0.1:8765"
)

def process_tick(data):
    # Your actual processing logic here
    symbol = data.get("symbol")
    quote = data.get("data", {})
    ltp = quote.get("ltp", 0)
    # ... strategy calculations, database writes, etc.

def on_tick(data):
    start = time.perf_counter()

    # Your processing logic
    process_tick(data)

    processing_time = (time.perf_counter() - start) * 1000

    if processing_time > 10:  # More than 10ms
        print(f"Slow processing: {processing_time:.1f}ms")

instruments_list = [
    {"exchange": "NSE_INDEX", "symbol": "NIFTY"}
]

client.connect()
client.subscribe_quote(instruments_list, on_data_received=on_tick)

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    client.unsubscribe_quote(instruments_list)
    client.disconnect()
```

### Combined Monitoring Example

A complete example that monitors all three metrics:

```python
from openalgo import api
import time
from collections import deque

client = api(
    api_key="your_api_key_here",
    host="http://127.0.0.1:5000",
    ws_url="ws://127.0.0.1:8765"
)

# Monitoring state
update_count = 0
start_time = time.time()
latencies = deque(maxlen=100)  # Keep last 100 latency measurements
processing_times = deque(maxlen=100)

def process_tick(data):
    # Your actual processing logic
    pass

def on_tick(data):
    global update_count
    receive_time = time.time() * 1000  # Convert to milliseconds
    proc_start = time.perf_counter()

    # Count updates
    update_count += 1

    # Measure latency (timestamp is in milliseconds)
    quote = data.get("data", {})
    broker_time = quote.get("timestamp", 0)
    if broker_time > 0:
        latency_ms = receive_time - broker_time
        latencies.append(latency_ms)

    # Process the tick
    process_tick(data)

    # Measure processing time
    processing_ms = (time.perf_counter() - proc_start) * 1000
    processing_times.append(processing_ms)

def print_stats():
    elapsed = time.time() - start_time
    if elapsed > 0:
        rate = update_count / elapsed
        avg_latency = sum(latencies) / len(latencies) if latencies else 0
        avg_processing = sum(processing_times) / len(processing_times) if processing_times else 0

        print(f"\n--- Performance Stats ---")
        print(f"Update rate: {rate:.1f}/sec")
        print(f"Avg latency: {avg_latency:.1f}ms")
        print(f"Avg processing: {avg_processing:.2f}ms")

        # Warnings
        if rate < 100:
            print("WARNING: Low update rate - check connection")
        if avg_latency > 100:
            print("WARNING: High latency detected")
        if avg_processing > 10:
            print("WARNING: Slow processing - optimize callback")

instruments_list = [
    {"exchange": "NSE_INDEX", "symbol": "NIFTY"},
    {"exchange": "NSE", "symbol": "RELIANCE"}
]

client.connect()
client.subscribe_quote(instruments_list, on_data_received=on_tick)

try:
    while True:
        time.sleep(10)
        print_stats()
except KeyboardInterrupt:
    client.unsubscribe_quote(instruments_list)
    client.disconnect()
```

## Error Handling

### Graceful Disconnection

```python
from openalgo import api
import time
import signal
import sys

client = api(
    api_key="your_api_key_here",
    host="http://127.0.0.1:5000",
    ws_url="ws://127.0.0.1:8765"
)

instruments_list = [
    {"exchange": "NSE_INDEX", "symbol": "NIFTY"}
]

def cleanup(signum=None, frame=None):
    print("\nCleaning up...")
    try:
        client.unsubscribe_quote(instruments_list)
        client.disconnect()
    except:
        pass
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def on_data_received(data):
    symbol = data.get("symbol")
    quote = data.get("data", {})
    ltp = quote.get("ltp", 0)
    print(f"Quote: {symbol} = {ltp}")

try:
    client.connect()
    client.subscribe_quote(instruments_list, on_data_received=on_data_received)

    while True:
        time.sleep(1)
except Exception as e:
    print(f"Error: {e}")
finally:
    cleanup()
```

### Connection Recovery

```python
from openalgo import api
import time

def create_client():
    return api(
        api_key="your_api_key_here",
        host="http://127.0.0.1:5000",
        ws_url="ws://127.0.0.1:8765"
    )

instruments_list = [
    {"exchange": "NSE_INDEX", "symbol": "NIFTY"}
]

def on_data_received(data):
    symbol = data.get("symbol")
    quote = data.get("data", {})
    ltp = quote.get("ltp", 0)
    print(f"Quote: {symbol} = {ltp}")

def run_with_recovery():
    while True:
        client = create_client()
        try:
            client.connect()
            client.subscribe_quote(instruments_list, on_data_received=on_data_received)

            while True:
                time.sleep(1)

        except Exception as e:
            print(f"Connection error: {e}")
            print("Reconnecting in 5 seconds...")
            try:
                client.disconnect()
            except:
                pass
            time.sleep(5)

run_with_recovery()
```

## Best Practices

1. **Always cleanup**: Use `try/finally` or signal handlers to ensure `unsubscribe_quote()` and `disconnect()` are called.

2. **Minimize callback processing**: Keep callback functions fast to avoid blocking the WebSocket receive loop.

3. **Use polling for heavy processing**: If you need to do heavy computation, use `get_quotes()` polling instead of callbacks.

4. **Handle reconnection**: Implement reconnection logic for production systems.

5. **Subscribe only to needed symbols**: Don't subscribe to more instruments than necessary to reduce bandwidth and processing.

6. **Use appropriate exchange codes**:
   - `NSE_INDEX` - NSE Indices (NIFTY, BANKNIFTY, etc.)
   - `NSE` - NSE Cash segment
   - `BSE` - BSE Cash segment
   - `NFO` - NSE Futures & Options
   - `BFO` - BSE Futures & Options
   - `MCX` - MCX Commodities
   - `CDS` - Currency Derivatives

## Comparison: LTP vs Quote vs Depth

| Feature | LTP | Quote | Depth |
|---------|-----|-------|-------|
| Last Traded Price | Yes | Yes | Yes |
| OHLC | No | Yes | Yes |
| Bid/Ask | No | Yes | Yes |
| Volume | No | Yes | Yes |
| Market Depth (5/20 levels) | No | No | Yes |
| Bandwidth | Low | Medium | High |
| Use Case | Price tracking | OHLC strategies | Order book analysis |

### When to Use Quote Feed

- Building OHLC-based indicators (RSI, MACD, etc.)
- Tracking day range and position within range
- Monitoring bid-ask spreads
- Volume-based strategies
- General market monitoring dashboards

## Related Documentation

- [Python SDK Documentation](python_sdk.md) - Complete SDK reference
- [WebSocket Usage Examples](websocket_usage_example.md) - Low-level WebSocket examples
- [WebSocket Optimization](WEBSOCKET_OPTIMIZATION.md) - Performance tuning guide
