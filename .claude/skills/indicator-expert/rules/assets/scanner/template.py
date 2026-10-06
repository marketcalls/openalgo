"""
Multi-Symbol Indicator Scanner — Screens stocks by technical conditions
"""
import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from dotenv import find_dotenv, load_dotenv
from openalgo import api, ta

script_dir = Path(__file__).resolve().parent
load_dotenv(find_dotenv(), override=False)

SCAN_TYPE = "rsi-oversold"  # Change to desired scan
EXCHANGE = "NSE"
INTERVAL = "D"
DAYS = 365

client = api(
    api_key=os.getenv("OPENALGO_API_KEY"),
    host=os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000"),
)

# Watchlist: NIFTY 50
NIFTY50 = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BPCL", "BHARTIARTL",
    "BRITANNIA", "CIPLA", "COALINDIA", "DIVISLAB", "DRREDDY",
    "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE",
    "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK",
    "INFY", "ITC", "JSWSTEEL", "KOTAKBANK", "LT",
    "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SUNPHARMA",
    "TCS", "TATACONSUM", "TATAMOTORS", "TATASTEEL", "TECHM",
    "TITAN", "ULTRACEMCO", "UPL", "WIPRO",
]


def fetch_data(symbol):
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=DAYS)
    try:
        df = client.history(
            symbol=symbol, exchange=EXCHANGE, interval=INTERVAL,
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
        )
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df = df.set_index("timestamp")
        else:
            df.index = pd.to_datetime(df.index)
        df = df.sort_index()
        if df.index.tz is not None:
            df.index = df.index.tz_convert(None)
        return df
    except Exception as e:
        print(f"  Error fetching {symbol}: {e}")
        return None


def scan_rsi_oversold(df, symbol):
    close = df["close"]
    rsi = ta.rsi(close, 14)
    val = rsi.iloc[-1]
    if val < 30:
        return {"symbol": symbol, "ltp": close.iloc[-1], "rsi": round(val, 2), "signal": "OVERSOLD"}
    return None


def scan_rsi_overbought(df, symbol):
    close = df["close"]
    rsi = ta.rsi(close, 14)
    val = rsi.iloc[-1]
    if val > 70:
        return {"symbol": symbol, "ltp": close.iloc[-1], "rsi": round(val, 2), "signal": "OVERBOUGHT"}
    return None


def scan_ema_crossover(df, symbol):
    close = df["close"]
    ema_fast = ta.ema(close, 10)
    ema_slow = ta.ema(close, 20)
    cross = ta.crossover(ema_fast, ema_slow)
    # Check last 3 bars for recent crossover
    if any(cross[-3:]):
        return {"symbol": symbol, "ltp": close.iloc[-1],
                "ema10": round(ema_fast.iloc[-1], 2),
                "ema20": round(ema_slow.iloc[-1], 2),
                "signal": "EMA CROSS UP"}
    return None


def scan_supertrend_buy(df, symbol):
    close = df["close"]
    high = df["high"]
    low = df["low"]
    st, direction = ta.supertrend(high, low, close, 10, 3.0)
    direction = pd.Series(direction, index=df.index)
    # Direction changed to uptrend in last 3 bars
    buy = (direction == -1) & (direction.shift(1) == 1)
    if any(buy.iloc[-3:]):
        return {"symbol": symbol, "ltp": close.iloc[-1],
                "supertrend": round(st[-1], 2),
                "signal": "SUPERTREND BUY"}
    return None


def scan_volume_spike(df, symbol):
    vol = df["volume"]
    avg_vol = ta.sma(vol, 20)
    if vol.iloc[-1] > 2 * avg_vol.iloc[-1]:
        return {"symbol": symbol, "ltp": df["close"].iloc[-1],
                "volume": int(vol.iloc[-1]),
                "avg_volume": int(avg_vol.iloc[-1]),
                "ratio": round(vol.iloc[-1] / avg_vol.iloc[-1], 2),
                "signal": "VOLUME SPIKE"}
    return None


# Scan dispatch
SCANNERS = {
    "rsi-oversold": scan_rsi_oversold,
    "rsi-overbought": scan_rsi_overbought,
    "ema-crossover": scan_ema_crossover,
    "supertrend-buy": scan_supertrend_buy,
    "volume-spike": scan_volume_spike,
}

scanner_fn = SCANNERS.get(SCAN_TYPE)
if not scanner_fn:
    print(f"Unknown scan type: {SCAN_TYPE}")
    print(f"Available: {', '.join(SCANNERS.keys())}")
    exit(1)

print(f"Scanning {len(NIFTY50)} symbols for: {SCAN_TYPE}")
print(f"Exchange: {EXCHANGE} | Interval: {INTERVAL}")
print("-" * 60)

results = []
for i, symbol in enumerate(NIFTY50, 1):
    print(f"  [{i}/{len(NIFTY50)}] {symbol}...", end="", flush=True)
    df = fetch_data(symbol)
    if df is not None and len(df) > 50:
        match = scanner_fn(df, symbol)
        if match:
            results.append(match)
            print(f" MATCH")
        else:
            print(f" -")
    else:
        print(f" skip")

print(f"\n{'='*60}")
print(f"Scan: {SCAN_TYPE} | Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print(f"Found: {len(results)} / {len(NIFTY50)} symbols")
print(f"{'='*60}")

if results:
    df_results = pd.DataFrame(results)
    print(df_results.to_string(index=False))
    output_file = script_dir / f"{SCAN_TYPE}_results.csv"
    df_results.to_csv(output_file, index=False)
    print(f"\nResults saved to: {output_file}")
else:
    print("No symbols matched the scan criteria.")
