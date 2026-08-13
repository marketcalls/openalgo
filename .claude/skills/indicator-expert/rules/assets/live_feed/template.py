"""
Real-Time Indicator Feed — WebSocket streaming with live indicator computation
"""
import os
import time
import numpy as np
from datetime import datetime, timedelta
from dotenv import find_dotenv, load_dotenv
from openalgo import api, ta

load_dotenv(find_dotenv(), override=False)

SYMBOL = "SBIN"
EXCHANGE = "NSE"
EMA_PERIOD = 20
RSI_PERIOD = 14
BUFFER_SIZE = 200

client = api(
    api_key=os.getenv("OPENALGO_API_KEY"),
    host=os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000"),
    verbose=1,
)

# Pre-fetch historical data for buffer initialization
print(f"Fetching historical data for {SYMBOL} buffer...")
try:
    df = client.history(
        symbol=SYMBOL, exchange=EXCHANGE, interval="1m",
        start_date=(datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d"),
        end_date=datetime.now().strftime("%Y-%m-%d"),
    )
    close_buffer = list(df["close"].values[-BUFFER_SIZE:])
    print(f"Buffer initialized with {len(close_buffer)} historical bars")
except Exception as e:
    print(f"Could not fetch history: {e}")
    close_buffer = []

instruments = [{"exchange": EXCHANGE, "symbol": SYMBOL}]
tick_count = 0
start_time = time.time()


def on_data(data):
    global tick_count
    ltp = data["data"].get("ltp")
    if ltp is None:
        return

    tick_count += 1
    close_buffer.append(float(ltp))

    # Keep buffer size capped
    if len(close_buffer) > BUFFER_SIZE:
        close_buffer.pop(0)

    if len(close_buffer) >= max(EMA_PERIOD, RSI_PERIOD + 1):
        arr = np.array(close_buffer, dtype=np.float64)
        ema_val = ta.ema(arr, EMA_PERIOD)[-1]
        rsi_val = ta.rsi(arr, RSI_PERIOD)[-1]

        # Determine bias
        if rsi_val > 70:
            bias = "OVERBOUGHT"
        elif rsi_val < 30:
            bias = "OVERSOLD"
        elif ltp > ema_val:
            bias = "BULLISH"
        else:
            bias = "BEARISH"

        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {SYMBOL:>10} "
              f"LTP:{ltp:>10.2f} | "
              f"EMA({EMA_PERIOD}):{ema_val:>10.2f} | "
              f"RSI({RSI_PERIOD}):{rsi_val:>6.2f} | "
              f"{bias}")


# Connect and subscribe
print(f"\nConnecting to WebSocket...")
client.connect()
client.subscribe_ltp(instruments, on_data_received=on_data)

print(f"Streaming {SYMBOL} on {EXCHANGE}")
print(f"Computing: EMA({EMA_PERIOD}), RSI({RSI_PERIOD})")
print(f"Press Ctrl+C to stop\n")
print(f"{'Time':<12} {'Symbol':>10} {'LTP':>12} {'EMA':>12} {'RSI':>8} {'Bias'}")
print("-" * 70)

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    elapsed = time.time() - start_time
    print(f"\n{'='*50}")
    print(f"Session Summary")
    print(f"Duration: {elapsed:.0f} seconds")
    print(f"Ticks received: {tick_count}")
    print(f"Ticks/sec: {tick_count / max(elapsed, 1):.1f}")
    print(f"Buffer size: {len(close_buffer)} bars")

# Cleanup
client.unsubscribe_ltp(instruments)
client.disconnect()
print("Disconnected.")
