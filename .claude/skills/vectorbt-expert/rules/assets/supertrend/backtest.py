"""
Supertrend Backtest - VectorBT + OpenAlgo
Strategy: Buy on uptrend crossover, sell on downtrend crossover.
           Intraday: entries 9:30-15:00, forced exit at 15:15.
Indicators: openalgo.ta.supertrend.
Fees: Indian intraday equity model (0.0225% + Rs 20/order).
Benchmark: NIFTY 50 Index via OpenAlgo (NSE_INDEX).
"""

import os
from datetime import datetime, timedelta, time
from pathlib import Path

import numpy as np
import pandas as pd
import vectorbt as vbt
from dotenv import find_dotenv, load_dotenv
from openalgo import api, ta

# --- Config ---
script_dir = Path(__file__).resolve().parent
load_dotenv(find_dotenv(), override=False)

SYMBOL = "SBIN"
EXCHANGE = "NSE"
INTERVAL = "5m"
ST_PERIOD = 10
ST_MULTIPLIER = 3.0
INIT_CASH = 1_000_000
FEES = 0.000225             # Indian intraday equity
FIXED_FEES = 20             # Rs 20 per order
ALLOCATION = 0.75
BENCHMARK_SYMBOL = "NIFTY"
BENCHMARK_EXCHANGE = "NSE_INDEX"

# --- Fetch Data ---
client = api(
    api_key=os.getenv("OPENALGO_API_KEY"),
    host=os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000"),
)

end_date = datetime.now().date()
start_date = end_date - timedelta(days=90)  # ~3 months for intraday

print(f"Fetching {SYMBOL} ({EXCHANGE}) {INTERVAL} data from {start_date} to {end_date}")

df = client.history(
    symbol=SYMBOL, exchange=EXCHANGE, interval=INTERVAL,
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

close = df["close"]
high = df["high"]
low = df["low"]
print(f"Data loaded: {len(df)} bars from {df.index[0]} to {df.index[-1]}")

# --- Strategy: Supertrend ---
st_line, st_direction = ta.supertrend(high, low, close, period=ST_PERIOD, multiplier=ST_MULTIPLIER)

t = df.index.time

cross_up = (close > st_line) & (close.shift(1) <= st_line.shift(1))
cross_down = (close < st_line) & (close.shift(1) >= st_line.shift(1))

# Indian market session windows
entry_window = (t >= time(9, 30)) & (t <= time(15, 0))
at_1515 = (t == time(15, 15))

long_entries = (cross_up & entry_window).fillna(False)
long_exits = (cross_down | at_1515).fillna(False)

entries = ta.exrem(long_entries, long_exits)
exits = ta.exrem(long_exits, entries)

print(f"Signals - Entries: {entries.sum()}, Exits: {exits.sum()}")

# --- Backtest ---
pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    init_cash=INIT_CASH,
    size=ALLOCATION,
    size_type="percent",
    fees=FEES,
    fixed_fees=FIXED_FEES,
    direction="longonly",
    min_size=1,
    size_granularity=1,
    freq="5min",
)

# --- Benchmark: NIFTY 50 Index (daily for comparison) ---
print(f"\nFetching benchmark: {BENCHMARK_SYMBOL} ({BENCHMARK_EXCHANGE})")
df_bench = client.history(
    symbol=BENCHMARK_SYMBOL, exchange=BENCHMARK_EXCHANGE, interval="D",
    start_date=start_date.strftime("%Y-%m-%d"),
    end_date=end_date.strftime("%Y-%m-%d"),
)
if "timestamp" in df_bench.columns:
    df_bench["timestamp"] = pd.to_datetime(df_bench["timestamp"])
    df_bench = df_bench.set_index("timestamp")
else:
    df_bench.index = pd.to_datetime(df_bench.index)
df_bench = df_bench.sort_index()
if df_bench.index.tz is not None:
    df_bench.index = df_bench.index.tz_convert(None)

bench_close = df_bench["close"]
pf_bench = vbt.Portfolio.from_holding(bench_close, init_cash=INIT_CASH, fees=FEES, freq="1D")

# --- Results ---
print("\n" + "=" * 60)
print(f"  Supertrend({ST_PERIOD}, {ST_MULTIPLIER}) Backtest - {SYMBOL} ({EXCHANGE} {INTERVAL})")
print("=" * 60)
print(pf.stats())

# --- Strategy vs Benchmark Metrics ---
print("\n--- Strategy vs Benchmark ---")
comparison = pd.DataFrame({
    "Strategy": [
        f"{pf.total_return() * 100:.2f}%",
        f"{pf.sharpe_ratio():.2f}",
        f"{pf.sortino_ratio():.2f}",
        f"{pf.max_drawdown() * 100:.2f}%",
        f"{pf.trades.win_rate() * 100:.1f}%",
        f"{pf.trades.count()}",
        f"{pf.trades.profit_factor():.2f}",
    ],
    f"Benchmark ({BENCHMARK_SYMBOL})": [
        f"{pf_bench.total_return() * 100:.2f}%",
        f"{pf_bench.sharpe_ratio():.2f}",
        f"{pf_bench.sortino_ratio():.2f}",
        f"{pf_bench.max_drawdown() * 100:.2f}%",
        "-", "-", "-",
    ],
}, index=["Total Return", "Sharpe Ratio", "Sortino Ratio", "Max Drawdown",
          "Win Rate", "Total Trades", "Profit Factor"])
print(comparison.to_string())

# --- Explain Backtest Report ---
print("\n--- Backtest Report Explanation ---")
print(f"* Total Return: {pf.total_return() * 100:.2f}% (intraday, squared off at 15:15)")
print(f"* Sharpe Ratio: {pf.sharpe_ratio():.2f} - risk-adjusted return")
print(f"* Max Drawdown: {pf.max_drawdown() * 100:.2f}% - worst intraday drawdown")
print(f"* Win Rate: {pf.trades.win_rate() * 100:.1f}% - Supertrend typically 35-45%")
print(f"* Profit Factor: {pf.trades.profit_factor():.2f} (>1.5 good)")
print(f"* Total Trades: {pf.trades.count()} - "
      f"{'sufficient' if pf.trades.count() >= 30 else 'too few - extend backtest period'}")

# --- Plot ---
fig = pf.plot(
    subplots=["value", "underwater", "cum_returns"],
    template="plotly_dark",
    title=f"Supertrend({ST_PERIOD},{ST_MULTIPLIER}) - {SYMBOL} ({EXCHANGE} {INTERVAL})",
)
fig.show()

# --- Export ---
trades_file = script_dir / f"{SYMBOL}_supertrend_trades.csv"
pf.positions.records_readable.to_csv(trades_file, index=False)
print(f"\nTrades exported to {trades_file}")
